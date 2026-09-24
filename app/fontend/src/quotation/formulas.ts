export type FormulaValue = string | number | boolean;
type Node = { kind: "literal"; value: FormulaValue } | { kind: "ref"; ref: string } | { kind: "range"; from: string; to: string } | { kind: "binary"; op: string; left: Node; right: Node } | { kind: "call"; name: string; args: Node[] };
export function columnIndex(label: string) { return [...label.replace(/\$/g, "").toUpperCase()].reduce((n,c) => n * 26 + c.charCodeAt(0)-64, 0)-1; }
export function columnLetter(index: number): string { let n=index+1,s=""; while(n>0){n--;s=String.fromCharCode(65+n%26)+s;n=Math.floor(n/26);} return s; }
export function parseAddress(value: string) { const m=/^\$?([A-Z]+)\$?(\d+)$/i.exec(value); return m ? { col:columnIndex(m[1]),row:Number(m[2]) } : null; }
export function shiftFormula(formula: string, dr: number, dc=0) {
  return formula.split(/("(?:[^"]|"")*")/).map((part,i) => i%2 ? part : part.replace(/(\$?)([A-Z]+)(\$?)(\d+)/gi, (_,ca,c,ra,r) => { const col=columnIndex(c)+(ca?0:dc), row=Number(r)+(ra?0:dr); return col<0||row<1 ? "#REF!" : `${ca}${columnLetter(col)}${ra}${row}`; })).join("");
}
/** Expand range arguments so references still follow their products after sorting. */
export function expandFormulaRanges(formula:string){
  const expanded=formula.split(/("(?:[^"]|"")*")/).map((part,i)=>i%2?part:part.replace(/(\$?)([A-Z]+)(\$?)(\d+):(\$?)([A-Z]+)(\$?)(\d+)/gi,(_,ca,c,ra,r,za,z,zra,zr)=>{
    const a={col:columnIndex(c),row:Number(r)},b={col:columnIndex(z),row:Number(zr)};
    if((Math.abs(a.col-b.col)+1)*(Math.abs(a.row-b.row)+1)>500)throw Error("Use a smaller formula range (up to 500 cells).");
    const refs:string[]=[];for(let row=Math.min(a.row,b.row);row<=Math.max(a.row,b.row);row++)for(let col=Math.min(a.col,b.col);col<=Math.max(a.col,b.col);col++)refs.push(`${ca&&za?"$":""}${columnLetter(col)}${ra&&zra?"$":""}${row}`);return refs.join(",");
  })).join("");if(expanded.length>5000)throw Error("Formula is too long.");return expanded;
}
export function evaluateFormula(formula: string, read: (ref: string) => FormulaValue): FormulaValue {
  try {
    if (formula.length>5000) throw Error("#VALUE!");
    const source=formula.replace(/^=/, ""), tokens:string[]=[];
    const re=/\s*(#REF!|"(?:[^"]|"")*"|\$?[A-Za-z]+\$?\d+|[A-Za-z]+|(?:\d+\.?\d*|\.\d+)|<=|>=|<>|[+\-*/(),:=<>])/gy;
    let offset=0;
    while(offset<source.length){re.lastIndex=offset;const m=re.exec(source);if(!m){if(!source.slice(offset).trim())break;throw Error("#NAME?");}tokens.push(m[1]);offset=re.lastIndex;}
    let pos=0;
    const precedence:Record<string,number>={"=":1,"<>":1,"<":1,">":1,"<=":1,">=":1,"+":2,"-":2,"*":3,"/":3};
    function atom():Node {
      const token=tokens[pos++];if(token==="#REF!")throw Error(token);if(!token)throw Error("#VALUE!");
      if(token==="(" ){const n=expr();if(tokens[pos++]!==")")throw Error("#VALUE!");return n;}
      if(token==="+"||token==="-")return {kind:"binary",op:token,left:{kind:"literal",value:0},right:atom()};
      if(token.startsWith('"'))return {kind:"literal",value:token.slice(1,-1).replace(/""/g,'"')};
      if(/^\d|^\./.test(token))return {kind:"literal",value:Number(token)};
      if(parseAddress(token)){if(tokens[pos]===":"){pos++;const to=tokens[pos++];if(!parseAddress(to))throw Error("#REF!");return {kind:"range",from:token,to};}return {kind:"ref",ref:token};}
      if(["TRUE","FALSE"].includes(token.toUpperCase()))return {kind:"literal",value:token.toUpperCase()==="TRUE"};
      if(tokens[pos++]!=="(")throw Error("#NAME?");const args:Node[]=[];
      if(tokens[pos]!==")")do{args.push(expr());if(tokens[pos]!==",")break;pos++;}while(pos<tokens.length);
      if(tokens[pos++]!==")")throw Error("#VALUE!");return {kind:"call",name:token.toUpperCase(),args};
    }
    function expr(min=0):Node {let left=atom();while(pos<tokens.length&&(precedence[tokens[pos]]??-1)>=min){const op=tokens[pos++];left={kind:"binary",op,left,right:expr(precedence[op]+1)};}return left;}
    const ast=expr();if(pos!==tokens.length)throw Error("#VALUE!");
    const num=(v:FormulaValue):number=>{if(typeof v==="string"&&v.startsWith("#"))throw Error(v);const n=Number(v);if(!Number.isFinite(n))throw Error("#VALUE!");return n;};
    const ev=(n:Node):FormulaValue=>{
      if(n.kind==="literal")return n.value;
      if(n.kind==="ref"){const v=read(n.ref);if(typeof v==="string"&&v.startsWith("#"))throw Error(v);return v;}
      if(n.kind==="range")throw Error("#VALUE!");
      if(n.kind==="binary"){const a=ev(n.left),b=ev(n.right);if(n.op==="=")return a===b;if(n.op==="<>")return a!==b;const x=num(a),y=num(b);if(n.op==="+")return x+y;if(n.op==="-")return x-y;if(n.op==="*")return x*y;if(n.op==="/"){if(!y)throw Error("#DIV/0!");return x/y;}if(n.op==="<")return x<y;if(n.op===">")return x>y;if(n.op==="<=")return x<=y;return x>=y;}
      if(n.name==="IF"){if(n.args.length!==3)throw Error("#VALUE!");return ev(n.args[ev(n.args[0])?1:2]);}
      const values:FormulaValue[]=[];
      for(const arg of n.args){if(arg.kind!=="range"){values.push(ev(arg));continue;}const a=parseAddress(arg.from)!,b=parseAddress(arg.to)!;if((Math.abs(b.row-a.row)+1)*(Math.abs(b.col-a.col)+1)>10000)throw Error("#VALUE!");for(let r=Math.min(a.row,b.row);r<=Math.max(a.row,b.row);r++)for(let c=Math.min(a.col,b.col);c<=Math.max(a.col,b.col);c++)values.push(read(columnLetter(c)+r));}
      const numbers=values.map(num);
      if(n.name==="SUM")return numbers.reduce((a,b)=>a+b,0);
      if(n.name==="MIN")return Math.min(...numbers);
      if(n.name==="MAX")return Math.max(...numbers);
      if(n.name==="ABS"&&numbers.length===1)return Math.abs(numbers[0]);
      if(n.name==="ROUND"&&numbers.length===2&&Math.abs(numbers[1])<=10){const scale=10**Math.trunc(numbers[1]);return Math.sign(numbers[0])*Math.round((Math.abs(numbers[0])+Number.EPSILON)*scale)/scale;}
      throw Error("#NAME?");
    };
    const value=ev(ast);return typeof value==="number"&&!Number.isFinite(value)?"#NUM!":value;
  } catch(e){return e instanceof Error&&/^#/.test(e.message)?e.message:"#VALUE!";}
}
