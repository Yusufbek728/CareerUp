from django.contrib.auth.models import User
from rest_framework import serializers
from .models import Job, resume, Internship

class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = "__all__"

class ResumeSerializer(serializers.ModelSerializer):
    class Meta:
        model = resume
        fields = "__all__"

class InternshipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Internship
        fields = "__all__"

        