from django.contrib.auth.models import User
from rest_framework import serializers
from .models import VendorProfile


class VendorProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorProfile
        fields = ['business_name', 'phone', 'address', 'logo']


class UserSerializer(serializers.ModelSerializer):
    vendor_profile = VendorProfileSerializer()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name',
                  'last_name', 'vendor_profile']

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('vendor_profile', {})
        # Update user fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        # Update or create profile
        profile, _ = VendorProfile.objects.get_or_create(user=instance)
        for attr, value in profile_data.items():
            setattr(profile, attr, value)
        profile.save()
        return instance


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    business_name = serializers.CharField(write_only=True)
    phone = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password',
                  'first_name', 'last_name', 'business_name', 'phone']

    def create(self, validated_data):
        business_name = validated_data.pop('business_name')
        phone = validated_data.pop('phone', '')
        user = User.objects.create_user(**validated_data)
        VendorProfile.objects.create(
            user=user,
            business_name=business_name,
            phone=phone,
        )
        return user