from rest_framework import serializers

from joatham_clients.models import Client


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ["id", "nom", "telephone", "email"]
        read_only_fields = ["id"]


class ClientCreateSerializer(serializers.Serializer):
    nom = serializers.CharField(max_length=100)
    telephone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
