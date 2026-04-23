from rest_framework import serializers

from joatham_apprenants.models import Apprenant, Formation, InscriptionFormation


class ApprenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Apprenant
        fields = [
            "id",
            "nom",
            "prenom",
            "telephone",
            "email",
            "adresse",
            "date_inscription",
            "actif",
            "observations",
        ]


class FormationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Formation
        fields = ["id", "nom", "description", "prix", "duree", "actif"]


class InscriptionSerializer(serializers.ModelSerializer):
    apprenant_nom = serializers.CharField(source="apprenant.nom", read_only=True)
    apprenant_prenom = serializers.CharField(source="apprenant.prenom", read_only=True)
    formation_nom = serializers.CharField(source="formation.nom", read_only=True)
    facture_numero = serializers.CharField(source="facture.numero", read_only=True)

    class Meta:
        model = InscriptionFormation
        fields = [
            "id",
            "apprenant",
            "apprenant_nom",
            "apprenant_prenom",
            "formation",
            "formation_nom",
            "facture",
            "facture_numero",
            "date_inscription",
            "statut",
            "montant_prevu",
            "montant_paye",
            "solde",
        ]
