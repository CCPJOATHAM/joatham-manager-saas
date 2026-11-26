from copy import deepcopy

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils.translation import override

from core.services.subscription import activate_subscription_for_entreprise, get_default_paid_plans
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.models import Abonnement
from .services.navigation import build_navigation_for_request
from .services.sidebar_presentation import build_sidebar_groups


class SidebarPresentationTests(SimpleTestCase):
    def test_unknown_links_and_badges_are_preserved_without_mutating_input(self):
        items = [dict(key=key, url='/unchanged/', label='Àvenir', is_active=True,
                      is_disabled=False, badge='Premium', badge_count=7)
                 for key in ('facture_list', 'future_module', 'dashboard')]
        original = deepcopy(items)
        groups = build_sidebar_groups(items)
        flattened = [{k: v for k, v in item.items() if k != 'icon'}
                     for group in groups for item in group['items']]
        self.assertCountEqual(flattened, original)
        self.assertEqual(items, original)
        self.assertTrue(all(group['items'] for group in groups))
        self.assertEqual(build_sidebar_groups([]), [])

    def test_disabled_link_is_not_clickable_and_active_link_has_accessible_state(self):
        items = [dict(key='facture_list', url='/invoices/', label='Àvenir', is_active=True),
                 dict(key='product_list', url='/forbidden/', label='Stock', is_disabled=True)]
        for language in ('fr', 'en'):
            with self.subTest(language=language), override(language):
                html = render_to_string('joatham_dashboard/includes/sidebar.html',
                                        {'sidebar_groups': build_sidebar_groups(items)})
                self.assertIn('aria-current="page"', html)
                self.assertIn('aria-disabled="true"', html)
                self.assertNotIn('href="/forbidden/"', html)
                self.assertIn('Àvenir', html)
                self.assertNotIn('<img', html)
                self.assertNotIn('login-logo.webp', html)
                self.assertNotIn('watermark', html)


class SidebarRoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = create_entreprise('Société Àvenir — Matadi')
        cls.other = create_entreprise('Entreprise B confidentielle')
        cls.users = {role: create_user('sidebar-' + role, role, cls.company if role != 'super_admin' else None)
                     for role in ('proprietaire', 'gestionnaire', 'comptable', 'super_admin')}
        cls.plans = [Abonnement.objects.create(**data, actif=True) for data in get_default_paid_plans()]

    def test_all_authorized_links_states_and_icons_are_preserved_for_roles_plans_and_languages(self):
        factory = RequestFactory()
        for plan in self.plans:
            activate_subscription_for_entreprise(entreprise=self.company, plan=plan,
                                                utilisateur=self.users['proprietaire'])
            for role, user in self.users.items():
                signatures = []
                for language in ('fr', 'en'):
                    with self.subTest(plan=plan.code, role=role, language=language), override(language):
                        request = factory.get(reverse('facture_list'))
                        request.user = user
                        items = build_navigation_for_request(request)
                        groups = build_sidebar_groups(items)
                        flat = [item for group in groups for item in group['items']]
                        self.assertTrue(flat)
                        self.assertCountEqual([{k: v for k, v in item.items() if k != 'icon'} for item in flat], items)
                        self.assertEqual(len({item['key'] for item in flat}), len(items))
                        html = render_to_string('joatham_dashboard/includes/sidebar.html', {
                            'sidebar_groups': groups, 'user_role_key': role,
                            'entreprise_identity': {'primary_name': self.company.nom} if role != 'super_admin' else {},
                        })
                        for item in items:
                            self.assertIn('data-nav-key="' + item['key'] + '"', html)
                        self.assertNotIn(self.other.nom, html)
                        if role != 'super_admin':
                            self.assertIn(self.company.nom, html)
                            self.assertNotIn('data-nav-key="super_admin_company_list"', html)
                        else:
                            self.assertNotIn(self.company.nom, html)
                        signatures.append([(item['key'], item['url'], item['is_disabled'], item['icon']) for item in flat])
                self.assertEqual(*signatures)

    def test_anonymous_navigation_is_empty(self):
        from django.contrib.auth.models import AnonymousUser
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        self.assertEqual(build_sidebar_groups(build_navigation_for_request(request)), [])
