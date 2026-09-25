from django.contrib.auth.password_validation import validate_password
from oauth2_provider.models import get_application_model
from rest_framework import serializers

from .models import BankCard, Company, Department, Notification, Position, Profile, User

Application = get_application_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=4)
    client_id = serializers.CharField(write_only=True)
    company_id = serializers.CharField(write_only=True, required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password', 'client_id', 'company_id')
        read_only_fields = ('id',)

    def validate_client_id(self, value):
        if not Application.objects.filter(client_id=value).exists():
            raise serializers.ValidationError('Unknown client_id.')
        return value

    def validate(self, attrs):
        company = None
        company_id = attrs.get('company_id')
        if company_id:
            try:
                company = Company.objects.get(pk=company_id)
            except Company.DoesNotExist:
                raise serializers.ValidationError({'company_id': 'Unknown company_id.'})

        if User.objects.filter(username=attrs['username'], company=company).exists():
            raise serializers.ValidationError({'username': 'Already registered for this company.'})

        attrs['company'] = company
        return attrs

    def create(self, validated_data):
        application = Application.objects.get(client_id=validated_data.pop('client_id'))
        validated_data.pop('company_id', None)
        company = validated_data.pop('company')
        password = validated_data.pop('password')
        user = User(application=application, company=company, **validated_data)
        user.set_password(password)
        user.save()
        return user


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = (
            'display_name', 'facebook_url', 'phone', 'avatar', 'avatar_preview_data_url', 'avatar_url',
            'cover', 'address', 'date_of_birth', 'bio',
        )
        read_only_fields = fields


class ProfileUpdateSerializer(serializers.Serializer):
    """Spans both User (họ tên) and Profile (display_name, facebook_url,
    avatar, cover, bio) — the models the client sees as one "thông tin cá
    nhân" form."""

    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    display_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    facebook_url = serializers.URLField(required=False, allow_blank=True)
    bio = serializers.CharField(required=False, allow_blank=True)
    avatar = serializers.ImageField(required=False)
    cover = serializers.ImageField(required=False)

    def save(self, **kwargs):
        user = self.context['request'].user
        data = self.validated_data

        user_fields = [f for f in ('first_name', 'last_name') if f in data]
        for field in user_fields:
            setattr(user, field, data[field])
        if user_fields:
            user.save(update_fields=user_fields)

        profile = user.profile
        profile_fields = [f for f in ('display_name', 'facebook_url', 'bio') if f in data]
        for field in profile_fields:
            setattr(profile, field, data[field])
        if profile_fields:
            profile.save(update_fields=profile_fields)

        if 'avatar' in data:
            from .services import update_avatar
            update_avatar(profile, data['avatar'])

        if 'cover' in data:
            from .services import update_cover
            update_cover(profile, data['cover'])

        return user


class BankCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankCard
        fields = ('id', 'bank_name', 'bin_code', 'account_holder', 'account_number', 'is_primary', 'created_at')
        read_only_fields = ('id', 'is_primary', 'created_at')


class PositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Position
        fields = ('id', 'name', 'level', 'created_at')
        read_only_fields = ('id', 'created_at')


class DepartmentSerializer(serializers.ModelSerializer):
    head_username = serializers.CharField(source='head.username', read_only=True, default=None)
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = ('id', 'name', 'parent', 'head', 'head_username', 'member_count', 'created_at')
        read_only_fields = ('id', 'head_username', 'member_count', 'created_at')

    def get_member_count(self, obj):
        return obj.members.filter(is_active=True).count()

    def validate_parent(self, value):
        if value is None:
            return value
        request = self.context['request']
        if value.company_id != request.user.company_id:
            raise serializers.ValidationError('Phòng ban cha phải thuộc cùng company.')
        node = value
        instance = self.instance
        while node is not None:
            if instance is not None and node.pk == instance.pk:
                raise serializers.ValidationError('Không thể tạo vòng lặp phòng ban.')
            node = node.parent
        return value

    def validate_head(self, value):
        if value is None:
            return value
        request = self.context['request']
        if value.company_id != request.user.company_id:
            raise serializers.ValidationError('Trưởng phòng phải thuộc cùng company.')
        return value


class UserAssignmentSerializer(serializers.Serializer):
    """Assigns (or clears, via null) a company member's department and/or
    position — the target user is passed in via context, not the URL body,
    since this always acts on one specific user."""

    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(), required=False, allow_null=True,
    )
    position = serializers.PrimaryKeyRelatedField(
        queryset=Position.objects.all(), required=False, allow_null=True,
    )

    def validate_department(self, value):
        if value is not None and value.company_id != self.context['request'].user.company_id:
            raise serializers.ValidationError('Phòng ban phải thuộc cùng công ty.')
        return value

    def validate_position(self, value):
        if value is not None and value.company_id != self.context['request'].user.company_id:
            raise serializers.ValidationError('Chức vụ phải thuộc cùng công ty.')
        return value

    def save(self, **kwargs):
        target = self.context['target']
        data = self.validated_data
        update_fields = [f for f in ('department', 'position') if f in data]
        for field in update_fields:
            setattr(target, field, data[field])
        if update_fields:
            target.save(update_fields=update_fields)
        return target


class CompanySerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source='plan.name', read_only=True, default=None)

    class Meta:
        model = Company
        fields = (
            'id', 'name', 'business_code', 'service_type', 'plan', 'plan_name',
            'contact_name', 'contact_email', 'contact_phone', 'address', 'created_at',
        )
        read_only_fields = fields


class ContactSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True, default=None)
    department_name = serializers.CharField(source='department.name', read_only=True, default=None)
    position_name = serializers.CharField(source='position.name', read_only=True, default=None)

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'role', 'role_name', 'department', 'department_name',
            'position', 'position_name', 'profile',
        )
        read_only_fields = fields


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = Notification
        fields = ('id', 'event', 'title', 'comment', 'payload', 'is_public', 'created_at', 'is_read')
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True, default=None)
    department_name = serializers.CharField(source='department.name', read_only=True, default=None)
    position_name = serializers.CharField(source='position.name', read_only=True, default=None)
    unread_notifications_count = serializers.SerializerMethodField()
    unread_messages_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'username', 'first_name', 'last_name', 'email', 'application', 'company', 'role', 'role_name',
            'department', 'department_name', 'position', 'position_name',
            'profile', 'must_change_password', 'unread_notifications_count', 'unread_messages_count',
        )
        read_only_fields = fields

    def get_unread_notifications_count(self, obj):
        if not obj.company_id:
            return 0
        return Notification.objects.visible_to(obj).exclude(reads__user=obj).count()

    def get_unread_messages_count(self, obj):
        if not obj.company_id:
            return 0
        from chat.services import total_unread_count
        return total_unread_count(obj)


class FirstChangePasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, min_length=4)
    def validate_new_password(self, value):
        validate_password(value, user=self.context['request'].user)
        return value

    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.must_change_password = False
        user.save(update_fields=['password', 'must_change_password'])
        return user

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=4)

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Mật khẩu hiện tại không đúng.')
        return value

    def validate_new_password(self, value):
        validate_password(value, user=self.context['request'].user)
        return value

    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.must_change_password = False
        user.save(update_fields=['password', 'must_change_password'])
        return user
