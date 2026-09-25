import logging

from accounts.permissions import MatchesCompanyHeader
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework.generics import ListAPIView, ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from store.models import Product

from .models import ProductRecipe, RecipeItem, StockCategory, StockItem, StockMovement
from .serializers import (
    ProduceRequestSerializer,
    ProductRecipeSerializer,
    ProductRecipeSetSerializer,
    RequiredMaterialSerializer,
    StockCategorySerializer,
    StockItemSerializer,
    StockMovementCreateSerializer,
    StockMovementSerializer,
)
from .services import movement_stats, produce, required_materials, stock_in, stock_out

logger = logging.getLogger(__name__)


class CompanyScopedMixin:
    """Every view here is company-scoped, matching the pattern in store/chat/accounts."""

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def perform_create(self, serializer):
        serializer.save(company_id=self.request.user.company_id)


class StockCategoryListCreateView(CompanyScopedMixin, ListCreateAPIView):
    serializer_class = StockCategorySerializer

    def get_queryset(self):
        return StockCategory.objects.filter(company_id=self.request.user.company_id)


class StockCategoryDetailView(CompanyScopedMixin, RetrieveUpdateDestroyAPIView):
    serializer_class = StockCategorySerializer

    def get_queryset(self):
        return StockCategory.objects.filter(company_id=self.request.user.company_id)


class StockItemListCreateView(CompanyScopedMixin, ListCreateAPIView):
    """?category=<id> filters. ?low_stock=1 returns only items at/below their
    reorder_level. quantity_on_hand is read-only here — it only moves through
    stock_in/stock_out so the ledger and the balance never drift apart.
    """

    serializer_class = StockItemSerializer

    def get_queryset(self):
        qs = StockItem.objects.filter(company_id=self.request.user.company_id).select_related('category')
        category_id = self.request.query_params.get('category')
        if category_id:
            qs = qs.filter(category_id=category_id)
        if self.request.query_params.get('low_stock'):
            qs = qs.filter(reorder_level__isnull=False, quantity_on_hand__lte=F('reorder_level'))
        return qs


class StockItemDetailView(CompanyScopedMixin, RetrieveUpdateDestroyAPIView):
    serializer_class = StockItemSerializer

    def get_queryset(self):
        return StockItem.objects.filter(company_id=self.request.user.company_id)


class StockMovementPagination(CursorPagination):
    page_size = 50
    max_page_size = 200
    ordering = '-id'


class StockMovementListView(CompanyScopedMixin, ListAPIView):
    """The in/out ledger. ?item=<id>&type=in|out&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD."""

    serializer_class = StockMovementSerializer
    pagination_class = StockMovementPagination

    def get_queryset(self):
        qs = StockMovement.objects.filter(company_id=self.request.user.company_id).select_related('item', 'created_by')
        item_id = self.request.query_params.get('item')
        if item_id:
            qs = qs.filter(item_id=item_id)
        movement_type = self.request.query_params.get('type')
        if movement_type:
            qs = qs.filter(movement_type=movement_type)
        date_from = self.request.query_params.get('date_from')
        if date_from:
            qs = qs.filter(occurred_date__gte=date_from)
        date_to = self.request.query_params.get('date_to')
        if date_to:
            qs = qs.filter(occurred_date__lte=date_to)
        return qs


class StockInView(APIView):
    """Record an inbound receipt (purchase, return, adjustment) and credit the item's balance."""

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, *args, **kwargs):
        serializer = StockMovementCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        item = get_object_or_404(StockItem, pk=data['item_id'], company_id=request.user.company_id)
        try:
            movement = stock_in(
                item, data['quantity'], request.user, unit_cost=data.get('unit_cost'),
                reference=data.get('reference', ''), occurred_at=data.get('occurred_at'),
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        logger.info('Stock in: item_id=%s qty=%s by user_id=%s', item.pk, data['quantity'], request.user.pk)
        return Response(StockMovementSerializer(movement).data, status=201)


class StockOutView(APIView):
    """Record an outbound consumption (sale, waste, manual adjustment) and debit the item's balance."""

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, *args, **kwargs):
        serializer = StockMovementCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        item = get_object_or_404(StockItem, pk=data['item_id'], company_id=request.user.company_id)
        try:
            movement = stock_out(
                item, data['quantity'], request.user,
                reference=data.get('reference', ''), occurred_at=data.get('occurred_at'),
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        logger.info('Stock out: item_id=%s qty=%s by user_id=%s', item.pk, data['quantity'], request.user.pk)
        return Response(StockMovementSerializer(movement).data, status=201)


class StockStatsView(APIView):
    """Nhập/xuất totals over time — ?group_by=day|month|year (default day),
    optional ?date_from=, ?date_to=, ?item=, ?category=.
    """

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def get(self, request, *args, **kwargs):
        group_by = request.query_params.get('group_by', 'day')
        if group_by not in ('day', 'month', 'year'):
            return Response({'detail': 'group_by phải là day, month hoặc year.'}, status=400)
        rows = movement_stats(
            company_id=request.user.company_id,
            group_by=group_by,
            date_from=request.query_params.get('date_from'),
            date_to=request.query_params.get('date_to'),
            item_id=request.query_params.get('item'),
            category_id=request.query_params.get('category'),
        )
        return Response(rows)


class ProductRecipeListView(CompanyScopedMixin, ListAPIView):
    """Every product that has a BOM defined — an overview "bom list"."""

    serializer_class = ProductRecipeSerializer

    def get_queryset(self):
        return (
            ProductRecipe.objects.filter(product__company_id=self.request.user.company_id)
            .select_related('product')
            .prefetch_related('items__stock_item')
        )


class ProductRecipeView(APIView):
    """GET: a product's current BOM (empty items if none set yet). PUT: replace it wholesale."""

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def get_product(self, request, product_id):
        return get_object_or_404(Product, pk=product_id, company_id=request.user.company_id)

    def get(self, request, product_id, *args, **kwargs):
        product = self.get_product(request, product_id)
        recipe = ProductRecipe.objects.filter(product=product).prefetch_related('items__stock_item').first()
        if recipe is None:
            return Response({'product': product.pk, 'product_name': product.name, 'note': '', 'items': [], 'updated_at': None})
        return Response(ProductRecipeSerializer(recipe).data)

    def put(self, request, product_id, *args, **kwargs):
        product = self.get_product(request, product_id)
        serializer = ProductRecipeSetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        stock_item_ids = [item['stock_item_id'] for item in data['items']]
        stock_items = {
            si.pk: si for si in StockItem.objects.filter(pk__in=stock_item_ids, company_id=request.user.company_id)
        }
        missing = set(stock_item_ids) - set(stock_items)
        if missing:
            return Response({'detail': f'Nguyên liệu không tồn tại: {sorted(missing)}'}, status=400)

        with transaction.atomic():
            recipe, _ = ProductRecipe.objects.get_or_create(product=product)
            recipe.note = data.get('note', '')
            recipe.save(update_fields=['note'])
            recipe.items.all().delete()
            RecipeItem.objects.bulk_create([
                RecipeItem(recipe=recipe, stock_item=stock_items[item['stock_item_id']], quantity=item['quantity'])
                for item in data['items']
            ])
        recipe.refresh_from_db()
        logger.info('Recipe set: product_id=%s items=%s by user_id=%s', product.pk, len(data['items']), request.user.pk)
        return Response(ProductRecipeSerializer(recipe).data)


class ProductRecipeCalculateView(APIView):
    """?quantity=N — explode the product's BOM into required raw materials vs
    current stock: the "how much do I need to import" calculator.
    """

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def get(self, request, product_id, *args, **kwargs):
        product = get_object_or_404(Product, pk=product_id, company_id=request.user.company_id)
        quantity = request.query_params.get('quantity', '1')
        try:
            materials = required_materials(product, quantity)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        return Response(RequiredMaterialSerializer(materials, many=True).data)


class ProductProduceView(APIView):
    """Actually consume the recipe to produce `quantity` units — deducts every
    ingredient from the warehouse and credits the output product's stock (if tracked).
    """

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, product_id, *args, **kwargs):
        product = get_object_or_404(Product, pk=product_id, company_id=request.user.company_id)
        serializer = ProduceRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            materials = produce(product, data['quantity'], request.user, reference=data.get('reference', ''))
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        logger.info('Produced: product_id=%s qty=%s by user_id=%s', product.pk, data['quantity'], request.user.pk)
        return Response(RequiredMaterialSerializer(materials, many=True).data, status=201)
