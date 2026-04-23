from rest_framework import serializers

from joatham_depenses.models import Depense


class DepenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Depense
        fields = ["id", "description", "montant", "date"]
        read_only_fields = ["id", "date"]
