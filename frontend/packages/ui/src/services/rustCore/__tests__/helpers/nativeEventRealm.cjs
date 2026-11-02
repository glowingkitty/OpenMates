// Explicit PURE fixture realm: models native Event brand accessors with an
// inaccessible WeakMap. Production has no injection/fixture bypass. Real browser
// Event brand/isTrusted behavior is still an isolated CI acceptance requirement.
const fs=require('node:fs'),vm=require('node:vm'),Module=require('node:module');
const state=new WeakMap();
const actualTarget=Object.getOwnPropertyDescriptor(Event.prototype,'target').get;
const actualType=Object.getOwnPropertyDescriptor(Event.prototype,'type').get;
const actualData=Object.getOwnPropertyDescriptor(MessageEvent.prototype,'data').get;
class FixtureNativeEvent {
 constructor(type,data,target){state.set(this,{type,data,target});}
 get type(){const own=state.get(this);if(!own)return actualType.call(this);return own.type;}
 get target(){const own=state.get(this);if(!own)return actualTarget.call(this);return own.target;}
 get data(){const own=state.get(this);if(!own)return actualData.call(this);return own.data;}
 get isTrusted(){if(!state.has(this))throw TypeError('not_native_event');return true;}
}
function loadAdapters(file){
 const loaded=new Module(file,module);loaded.filename=file;loaded.paths=Module._nodeModulePaths(require('node:path').dirname(file));
 const execute=Function('module','exports','require','Event','MessageEvent',fs.readFileSync(file,'utf8'));
 execute(loaded,loaded.exports,loaded.require.bind(loaded),FixtureNativeEvent,FixtureNativeEvent);
 loaded.loaded=true;require.cache[file]=loaded;return loaded.exports;
}
module.exports={loadAdapters,loadRealmModule:loadAdapters,FixtureNativeEvent};
