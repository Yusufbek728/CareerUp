from django.contrib.auth.models import User
from rest_framework import serializers
from django.contrib.auth.models import User
from .models import AccountProfile, Job, resume, Internship


class RegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    role = serializers.ChoiceField(choices=('company', 'worker'), write_only=True)
    display_name = serializers.CharField(write_only=True, max_length=200)

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'role', 'display_name')

    def create(self, validated_data):
        role = validated_data.pop('role')
        display_name = validated_data.pop('display_name')
        user = User.objects.create_user(**validated_data)
        AccountProfile.objects.create(user=user, role=role, display_name=display_name)
        return user

class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = "__all__"
        read_only_fields = ('owner',)

class ResumeSerializer(serializers.ModelSerializer):
    class Meta:
        model = resume
        fields = "__all__"
        read_only_fields = ('owner',)

class InternshipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Internship
        fields = "__all__"
        read_only_fields = ('owner',)

        