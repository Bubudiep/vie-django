from django.urls import path

from .api import (
    ProductProduceView,
    ProductRecipeCalculateView,
    ProductRecipeListView,
    ProductRecipeView,
    StockCategoryDetailView,
    StockCategoryListCreateView,
    StockInView,
    StockItemDetailView,
    StockItemListCreateView,
    StockMovementListView,
    StockOutView,
    StockStatsView,
)

app_name = 'inventory'
urlpatterns = [
    path('categories/', StockCategoryListCreateView.as_view(), name='categories'),
    path('categories/<int:pk>/', StockCategoryDetailView.as_view(), name='category-detail'),
    path('items/', StockItemListCreateView.as_view(), name='items'),
    path('items/<int:pk>/', StockItemDetailView.as_view(), name='item-detail'),
    path('movements/', StockMovementListView.as_view(), name='movements'),
    path('stock-in/', StockInView.as_view(), name='stock-in'),
    path('stock-out/', StockOutView.as_view(), name='stock-out'),
    path('stats/', StockStatsView.as_view(), name='stats'),
    path('recipes/', ProductRecipeListView.as_view(), name='recipes'),
    path('products/<int:product_id>/recipe/', ProductRecipeView.as_view(), name='product-recipe'),
    path('products/<int:product_id>/recipe/calculate/', ProductRecipeCalculateView.as_view(), name='product-recipe-calculate'),
    path('products/<int:product_id>/recipe/produce/', ProductProduceView.as_view(), name='product-recipe-produce'),
]
