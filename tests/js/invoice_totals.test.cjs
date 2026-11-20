const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {runInNewContext} = require('node:vm');
const context = {window: {}};
runInNewContext(readFileSync('static/joatham_dashboard/js/invoice-totals.js', 'utf8'), context);
const calculate = (rows, rates = {}) => JSON.parse(JSON.stringify(context.window.JoathamInvoiceTotals.calculate(rows, rates)));

test('105 x 500 and multiple lines match stored invoice Decimal totals', () => {
    assert.equal(calculate([{quantity: '105', price: '500'}]).ht, '52500.00');
    assert.deepEqual(calculate([{quantity: '105', price: '500'}, {quantity: '2', price: '99.99'}],
        {tva: '16', remise: '5', rabais: '2', ristourne: '1'}), {
        lines: ['52500.00', '199.98'], quantity: '107', ht: '52699.98',
        tax: '8432.00', discount: '4216.00', net: '56915.98',
    });
});

test('rounds the final Decimal expression, independently of displayed components', () => {
    assert.deepEqual(calculate([{quantity: '3', price: '0.10'}, {quantity: '7', price: '0.20'}], {tva: '16', remise: '5'}), {
        lines: ['0.30', '1.40'], quantity: '10', ht: '1.70', tax: '0.27', discount: '0.09', net: '1.89',
    });
    assert.equal(calculate([{quantity: '1', price: '0.01'}], {tva: '50'}).net, '0.02');
});

test('each quantity, unit price, tax and discount edit recalculates independently', () => {
    const rows = [{quantity: '2', price: '10.25'}];
    assert.equal(calculate(rows).net, '20.50');
    rows[0].quantity = '3'; assert.equal(calculate(rows).net, '30.75');
    rows[0].price = '15.50'; assert.equal(calculate(rows).net, '46.50');
    for (const name of ['remise', 'rabais', 'ristourne']) {
        assert.equal(calculate(rows, {[name]: '10'}).net, '41.85');
    }
    assert.equal(calculate(rows, {tva: '10'}).net, '51.15');
    assert.equal(calculate([]).net, '0.00');
    assert.equal(calculate([{quantity: '', price: ''}]).net, '0.00');
});
