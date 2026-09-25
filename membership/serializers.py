from rest_framework import serializers

from .models import (
    CardTransaction,
    CustomerVoucher,
    Event,
    MembershipCard,
    MembershipPlan,
    PointsAccount,
    PointsRedemptionOption,
    PointsTransaction,
    Voucher,
)


class MembershipPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = MembershipPlan
        fields = ('id', 'name', 'minutes', 'price', 'order')
        read_only_fields = fields


class MembershipCardSerializer(serializers.ModelSerializer):
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = MembershipCard
        fields = ('id', 'remaining_minutes', 'expires_at', 'is_expired', 'updated_at')
        read_only_fields = fields


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ('id', 'title', 'description', 'image', 'start_time', 'end_time', 'created_at')
        read_only_fields = fields


class CardTransactionSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source='plan.name', read_only=True, default=None)

    class Meta:
        model = CardTransaction
        fields = ('id', 'kind', 'minutes', 'plan', 'plan_name', 'session', 'note', 'created_at')
        read_only_fields = fields


class PointsAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = PointsAccount
        fields = ('id', 'balance', 'updated_at')
        read_only_fields = fields


class PointsTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PointsTransaction
        fields = ('id', 'kind', 'points', 'session', 'note', 'created_at')
        read_only_fields = fields


class PointsRedemptionOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PointsRedemptionOption
        fields = ('id', 'label', 'points_cost', 'minutes_reward', 'order')
        read_only_fields = fields


class VoucherSerializer(serializers.ModelSerializer):
    class Meta:
        model = Voucher
        fields = ('id', 'title', 'description', 'discount_type', 'discount_value')
        read_only_fields = fields


class CustomerVoucherSerializer(serializers.ModelSerializer):
    voucher = VoucherSerializer(read_only=True)
    is_usable = serializers.BooleanField(read_only=True)

    class Meta:
        model = CustomerVoucher
        fields = ('id', 'voucher', 'status', 'is_usable', 'expires_at', 'used_at', 'created_at')
        read_only_fields = fields
