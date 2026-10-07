const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
(async () => {
  const elements = new Map();
  const element = key => {
    if (!elements.has(key)) elements.set(key, {value:'',innerHTML:'',listeners:{},elements:new Proxy({}, {get:()=>({value:''})}),addEventListener(type,fn){this.listeners[type]=fn;}});
    return elements.get(key);
  };
  let images = {hero:'assets/hero.png',manifesto:'assets/detail.png',header_watermark:'assets/logo.png',footer_logo:'assets/footer.png'};
  const context = vm.createContext({document:{querySelector:element,querySelectorAll:()=>[]},sessionStorage:{getItem:()=>null},fetch:async(path,options={})=>{
    if(options.method==='POST' && path==='/api/admin/site-images')images={...images,...JSON.parse(options.body)};
    return {ok:true,text:async()=>JSON.stringify({images})};
  },console});
  let script = fs.readFileSync('admin.js','utf8');
  script = script.slice(0,script.indexOf('(async () => { if (sessionStorage.getItem(ADMIN_TAB_KEY)'));
  vm.runInContext(script,context);
  await vm.runInContext('loadSiteImages()',context);
  const html=element('#siteImageList').innerHTML;
  assert.equal((html.match(/data-site-image=/g)||[]).length,4);
  assert.ok(html.includes('Foto da se\u00e7\u00e3o O jeito Lumi'.replace(/\\u([a-f0-9]{4})/g,(_,hex)=>String.fromCharCode(parseInt(hex,16)))));
  const img={src:images.hero}, message={textContent:''},button={disabled:false};
  const form={dataset:{siteImage:'hero'},elements:{image:{value:'https://example.com/cappuccino.jpg'},image_file:{files:[],value:''}},querySelector:selector=>selector==='img'?img:selector==='.site-image-message'?message:button};
  let prevented=false;
  await element('#siteImageList').listeners.submit({target:{closest:()=>form},preventDefault(){prevented=true;}});
  assert.ok(prevented);
  assert.equal(images.hero,'https://example.com/cappuccino.jpg');
  assert.equal(img.src,images.hero);
  assert.equal(button.disabled,false);
  assert.ok(message.textContent.startsWith('Imagem salva!'));
  const targets=new Map();
  const storeContext=vm.createContext({document:{querySelector:selector=>{
    if(!targets.has(selector))targets.set(selector,{src:'old.png',getAttribute:()=> 'old.png',addEventListener(){}});
    return targets.get(selector);
  }},fetch:async()=>({ok:true,json:async()=>({images})})});
  const app=fs.readFileSync('app.js','utf8');
  vm.runInContext(app.slice(app.lastIndexOf('async function loadSiteImages'),app.lastIndexOf('loadSiteImages();')),storeContext);
  await vm.runInContext('loadSiteImages()',storeContext);
  assert.equal(targets.get('.hero-image-wrap>img').src,images.hero);
  assert.equal(targets.get('footer .brand-logo').src,images.footer_logo);
  assert.equal(targets.size,4);
  console.log('Admin image editing and storefront image loading passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
