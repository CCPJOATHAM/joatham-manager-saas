const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {runInNewContext} = require('node:vm');
const context = {window: {}};
runInNewContext(readFileSync('static/joatham_dashboard/js/subscription-estimate.js', 'utf8'), context);
const present = (...args) => context.window.JoathamSubscriptionEstimate.present(...args);
const currencies = JSON.parse(readFileSync('docs/currency-coverage.json', 'utf8')).currencies;
const unavailable = {fr: 'Conversion temporairement indisponible.', en: 'Conversion temporarily unavailable.'};

test('every application currency renders available and unavailable states in FR and EN', () => {
    for (const language of ['fr', 'en']) for (const {code} of currencies) {
        const data = {currency_code: code, amount_usd: '20.00', estimated_amount: '28.50', exchange_rate: '1.425'};
        const available = present(data, language, code, unavailable[language]);
        assert.equal(available.available, true, `${language} ${code}`);
        assert.equal(available.currency, code);
        assert.equal(available.reference, language === 'fr' ? '20,00' : '20.00');
        assert.equal(available.amount, language === 'fr' ? '28,50' : '28.50');
        const missing = present({...data, estimated_amount: null, exchange_rate: null}, language, code, unavailable[language]);
        assert.equal(missing.available, false);
        assert.equal(missing.amount, unavailable[language]);
        assert.equal(missing.rate, '—');
        assert.equal(missing.reference, available.reference);
    }
});

test('EUR -> unavailable KPW -> JPY -> EUR recovers immediately without stale amounts', () => {
    for (const language of ['fr', 'en']) {
        const sequence = [
            ['EUR', '18.00', '0.9', true], ['KPW', null, null, false],
            ['JPY', '3000.00', '150', true], ['EUR', '18.00', '0.9', true],
        ];
        for (const [currency, amount, rate, expected] of sequence) {
            const view = present({currency_code: currency, amount_usd: '20.00', estimated_amount: amount, exchange_rate: rate}, language, currency, unavailable[language]);
            assert.equal(view.available, expected);
            assert.equal(view.currency, currency);
            if (expected) assert.notEqual(view.amount, unavailable[language]);
            else assert.equal(view.rate, '—');
        }
        const annual = present({currency_code: 'EUR', amount_usd: '192.00', estimated_amount: '172.80', exchange_rate: '.9'}, language, 'EUR', unavailable[language]);
        assert.equal(annual.reference, language === 'fr' ? '192,00' : '192.00');
        assert.equal(annual.amount, language === 'fr' ? '172,80' : '172.80');
    }
});

test('missing/invalid rates and stale currency data never show zero, None or NaN as an estimate', () => {
    for (const rate of [null, undefined, '', 'None', 'NaN', 'Infinity', 0, -1, true]) {
        const view = present({currency_code: 'CAD', amount_usd: '20', estimated_amount: '27', exchange_rate: rate}, 'en', 'CAD', unavailable.en);
        assert.equal(view.available, false);
        assert.equal(view.amount, unavailable.en);
        assert.equal(view.rate, '—');
    }
    for (const amount of [null, undefined, '', 'None', 'NaN', 'Infinity', -1, false]) {
        assert.equal(present({currency_code: 'CAD', amount_usd: '20', estimated_amount: amount, exchange_rate: '1.35'}, 'fr', 'CAD', unavailable.fr).available, false);
    }
    const stale = present({currency_code: 'CAD', amount_usd: '20', estimated_amount: '27', exchange_rate: '1.35'}, 'en', 'EUR', unavailable.en);
    assert.equal(stale.currency, 'EUR');
    assert.equal(stale.available, false);
    assert.equal(stale.amount, unavailable.en);
    assert.equal(present({currency_code: 'USD', amount_usd: '0', estimated_amount: '0', exchange_rate: '1'}, 'en', 'USD', unavailable.en).available, true);
});
