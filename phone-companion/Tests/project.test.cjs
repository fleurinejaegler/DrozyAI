'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
// Parse the OpenStep project format, then check the target/file graph without Xcode.
function parseProject(text){
  const tokens=[];let i=0;
  while(i<text.length){
    if(/\s/.test(text[i])){i++;continue;}
    if(text.slice(i,i+2)==='//'){const end=text.indexOf('\n',i);i=end<0?text.length:end+1;continue;}
    if(text.slice(i,i+2)==='/*'){const end=text.indexOf('*/',i+2);assert.notEqual(end,-1);i=end+2;continue;}
    if(text[i]==='"'){
      let j=i+1;while(j<text.length){if(text[j]==='\\'){j+=2;continue;}if(text[j]==='"')break;j++;}
      assert.ok(j<text.length);tokens.push(JSON.parse(text.slice(i,j+1)));i=j+1;continue;
    }
    if('{}()=;,'.includes(text[i])){tokens.push(text[i++]);continue;}
    let j=i;while(j<text.length&&!/[\s{}()=;,]/.test(text[j]))j++;
    tokens.push(text.slice(i,j));i=j;
  }
  let position=0;
  const expect=token=>assert.equal(tokens[position++],token);
  function value(){
    if(tokens[position]==='{'){
      position++;const object=Object.create(null);
      while(tokens[position]!=='}'){
        const key=tokens[position++];assert.ok(key!==undefined);assert.ok(!(key in object),`Duplicate key ${key}`);
        expect('=');object[key]=value();expect(';');
      }
      position++;return object;
    }
    if(tokens[position]==='('){
      position++;const array=[];
      while(tokens[position]!==')'){array.push(value());if(tokens[position]!==')')expect(',');}
      position++;return array;
    }
    assert.ok(position<tokens.length);return tokens[position++];
  }
  const result=value();assert.equal(position,tokens.length);return result;
}
test('Xcode project parses and all file/build/target references resolve',()=>{
  const root=path.join(__dirname,'..');const project=parseProject(fs.readFileSync(path.join(root,'DrowsyRelay.xcodeproj/project.pbxproj'),'utf8'));
  const objects=project.objects;assert.equal(objects[project.rootObject].isa,'PBXProject');
  for(const object of Object.values(objects)){
    for(const key of ['buildConfigurationList','mainGroup','productRefGroup','productReference','target','targetProxy','containerPortal','remoteGlobalIDString','package','productRef','fileRef'])if(object[key])assert.ok(objects[object[key]],`Missing ${key}: ${object[key]}`);
    for(const key of ['children','files','buildPhases','targets','packageReferences','packageProductDependencies','buildConfigurations','dependencies'])for(const ref of object[key]||[])assert.ok(objects[ref],`Missing ${key}: ${ref}`);
  }
  function visit(ref,parent){
    const object=objects[ref];
    if(object.isa==='PBXGroup'){
      const location=object.path?path.join(parent,object.path):parent;
      for(const child of object.children)visit(child,location);
    }else if(object.isa==='PBXFileReference'&&object.sourceTree!=='BUILT_PRODUCTS_DIR'){
      const location=path.join(object.sourceTree==='SOURCE_ROOT'?root:parent,object.path);
      assert.ok(fs.existsSync(location),`Missing source/resource: ${location}`);
    }
  }
  visit(objects[project.rootObject].mainGroup,root);
  const configurations=Object.values(objects).filter(item=>item.isa==='XCBuildConfiguration'&&item.buildSettings.INFOPLIST_FILE);
  assert.equal(configurations.length,2);
  for(const config of configurations)assert.ok(fs.existsSync(path.join(root,config.buildSettings.INFOPLIST_FILE)));
  assert.match(fs.readFileSync(path.join(root,'DrowsyRelay/Info-Debug.plist'),'utf8'),/NSAllowsArbitraryLoads<\/key><true\/>/);
  assert.match(fs.readFileSync(path.join(root,'DrowsyRelay/Info.plist'),'utf8'),/NSAllowsArbitraryLoads<\/key><false\/>/);
});
