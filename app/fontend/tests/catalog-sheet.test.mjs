import test from 'node:test';
import assert from 'node:assert/strict';
import { parseSheetPaste, normalizeSheetValue } from '../src/quotation/sheetData.ts';

test('Excel TSV maps prices and quantities across consecutive product rows', () => {
  const result = parseSheetPaste('12.50\t25\r\n18\t100\r\n', ['a','b'], ['price','quantity','amount','note'], 0, 0);
  assert.deepEqual(result, { patches:[{sku:'a',patch:{price:'12.50',quantity:'25'}},{sku:'b',patch:{price:'18',quantity:'100'}}], invalid:0, clipped:0 });
});
test('read-only columns keep alignment when pasting an Excel rectangle', () => {
  const result = parseSheetPaste('12\t5\t60\tBlue', ['a'], ['price','quantity','amount','note'], 0, 0);
  assert.deepEqual(result.patches, [{sku:'a',patch:{price:'12',quantity:'5',note:'Blue'}}]);
});
test('invalid numbers and out-of-range cells are reported before applying a paste', () => {
  const result = parseSheetPaste('-5\t1.5\n2\t3', ['a'], ['price','quantity'], 0, 0);
  assert.equal(result.invalid,2); assert.equal(result.clipped,1);
  assert.equal(normalizeSheetValue('price','1,234.50'),'1234.50');
  assert.equal(normalizeSheetValue('price','12.'),'12');
  assert.equal(normalizeSheetValue('quantity',''),'');
  assert.equal(normalizeSheetValue('quantity','=1+1'),null);
  assert.equal(normalizeSheetValue('note','=1+1'),'=1+1');
});
