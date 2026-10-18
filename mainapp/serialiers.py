from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import AccountProfile, Job, Resume, Internship, check_city_belongs_to_country


class RegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    role = serializers.ChoiceField(choices=('company', 'worker'), write_only=True)
    display_name = serializers.CharField(write_only=True, max_length=200)

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'role', 'display_name')

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('This username is already taken.')
        return value

    def validate_password(self, value):
        validate_password(value, user=User(username=self.initial_data.get('username', '')))
        return value

    def create(self, validated_data):
        role = validated_data.pop('role')
        display_name = validated_data.pop('display_name')
        user = User.objects.create_user(**validated_data)
        AccountProfile.objects.create(user=user, role=role, display_name=display_name)
        return user

class CountryCitySerializerMixin:
    """The city must belong to the country (also on PATCH, falling back to the stored values)."""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = getattr(self, 'instance', None)
        country = attrs['country'] if 'country' in attrs else getattr(instance, 'country', None)
        city = attrs['city'] if 'city' in attrs else getattr(instance, 'city', None)
        try:
            check_city_belongs_to_country(country, city)
        except DjangoValidationError as error:
            raise serializers.ValidationError({'city': error.messages})
        return attrs


class JobSerializer(CountryCitySerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = "__all__"
        read_only_fields = ('owner', 'view_count')

class ResumeSerializer(CountryCitySerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Resume
        fields = "__all__"
        read_only_fields = ('owner', 'view_count')

class InternshipSerializer(CountryCitySerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Internship
        fields = "__all__"
        read_only_fields = ('owner', 'view_count')

        