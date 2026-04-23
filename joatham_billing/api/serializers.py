from rest_framework import serializers

from joatham_billing.models import Facture, LigneFacture, PaiementFacture


class LigneFactureSerializer(serializers.ModelSerializer):
    class Meta:
        model = LigneFacture
        fields = ["designation", "quantite", "prix_unitaire"]


class PaiementFactureSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaiementFacture
        fields = ["id", "montant", "mode", "reference", "date_paiement", "statut", "note"]
        read_only_fields = ["id", "statut"]


class FactureSerializer(serializers.ModelSerializer):
    lignes = LigneFactureSerializer(many=True, read_only=True)
    total_paye = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    reste_a_payer = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Facture
        fields = [
            "id",
            "numero",
            "client",
            "client_nom",
            "date",
            "statut",
            "montant",
            "tva",
            "remise",
            "rabais",
            "ristourne",
            "total_paye",
            "reste_a_payer",
            "lignes",
        ]
        read_only_fields = ["id", "numero", "date", "montant", "total_paye", "reste_a_payer"]


class FactureCreateSerializer(serializers.Serializer):
    client = serializers.IntegerField(required=False, allow_null=True)
    client_nom = serializers.CharField(required=False, allow_blank=True)
    tva = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=0)
    remise = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=0)
    rabais = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=0)
    ristourne = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=0)
    lignes = LigneFactureSerializer(many=True)


class FactureStatusSerializer(serializers.Serializer):
    statut = serializers.ChoiceField(choices=Facture.Statut.choices)
    note = serializers.CharField(required=False, allow_blank=True)


class FacturePaymentSerializer(serializers.Serializer):
    montant = serializers.DecimalField(max_digits=10, decimal_places=2)
    mode = serializers.ChoiceField(choices=PaiementFacture.ModePaiement.choices)
    reference = serializers.CharField(required=False, allow_blank=True)
    note = serializers.CharField(required=False, allow_blank=True)
