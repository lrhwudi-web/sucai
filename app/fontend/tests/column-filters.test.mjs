import test from 'node:test';
import assert from 'node:assert/strict';
import {filteredRecords,filterOptions,matchesFilter,searchOptions,toggleOptions,selectedValueFilter} from '../src/quotation/columnFilters.ts';

const rows=[
 {product:'1',values:{category:'Cover',brand:'Craftsman',inventory:'0',note:''}},
 {product:'2',values:{category:'Driver Cover',brand:'Craftsman',inventory:'10',note:'NEW'}},
 {product:'3',values:{category:'Cover',brand:'Big Teeth',inventory:'2',note:''}},
 {product:'4',values:{category:'Glove Case',brand:'Craftsman',inventory:'10',note:'NEW'}},
 {product:'5',values:{category:'',brand:'Craftsman',inventory:'',note:''}},
];
const values=(...values)=>({kind:'values',values});
test('checkboxes match exact values, OR within columns and AND across columns',()=>{
 assert.deepEqual(filteredRecords(rows,{category:values('Cover','Glove Case'),brand:values('Craftsman')}).map(r=>r.product),['1','4']);
 assert.deepEqual(filteredRecords(rows,{category:values('')}).map(r=>r.product),['5']);
 assert.deepEqual(filteredRecords(rows,{inventory:values('0')}).map(r=>r.product),['1']);
 assert.deepEqual(filteredRecords(rows,{category:values()}).map(r=>r.product),[]);
});
test('facets count other-filter matches and retain currently unchecked alternatives and blanks',()=>{
 const filters={category:values('Cover'),brand:values('Craftsman')};
 assert.deepEqual(filterOptions(rows,filters,'category'),[{value:'Cover',count:1},{value:'Driver Cover',count:1},{value:'Glove Case',count:1},{value:'',count:1}]);
 assert.deepEqual(filterOptions(rows,filters,'brand'),[{value:'Craftsman',count:1},{value:'Big Teeth',count:1}]);
 assert.deepEqual(filterOptions(rows.slice(0,2),{},'note'),[{value:'',count:1},{value:'NEW',count:1}]);
});
test('keyword search uses any word, ignores case, and supports blanks without an 80-value limit',()=>{
 const options=filterOptions(rows,{},'category');
 assert.deepEqual(searchOptions(options,'DRIVER glove').map(o=>o.value),['Driver Cover','Glove Case']);
 assert.deepEqual(searchOptions(options,'blanks').map(o=>o.value),['']);
 assert.equal(searchOptions(Array.from({length:200},(_,i)=>({value:String(i),count:1})),'').length,200);
});
test('search-scoped select all preserves the pending choices outside the search and does not mutate them',()=>{
 const options=filterOptions(rows,{},'category'),all=new Set(options.map(o=>o.value)),shown=searchOptions(options,'cover');
 const pending=toggleOptions(all,shown,false);
 assert.equal(all.size,4);assert.deepEqual([...pending],['Glove Case','']);
 assert.deepEqual(selectedValueFilter(toggleOptions(pending,shown,true),options,'cover'),values('Cover','Driver Cover'));
 assert.equal(selectedValueFilter(all,options,''),undefined);
 assert.deepEqual(selectedValueFilter(pending,options,''),values('Glove Case',''));
});
test('text conditions are case insensitive and can explicitly match blank values',()=>{
 for(const [operator,query,match] of [['contains','cover',true],['notContains','cover',false],['equals','Driver Cover',true],['notEquals','Cover',true],['startsWith','driver',true],['endsWith','COVER',true]]){
  assert.equal(matchesFilter('Driver Cover',{kind:'text',operator,query}),match);
 }
 assert.equal(matchesFilter('',{kind:'text',operator:'equals',query:''}),true);
 assert.equal(matchesFilter('0',{kind:'text',operator:'equals',query:''}),false);
});
