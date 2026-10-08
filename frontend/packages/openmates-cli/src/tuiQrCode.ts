/** Local terminal QR rendering. Never send a share URL to a remote image service. */
import qrcode from 'qrcode-terminal';
import { cells } from './tuiText.js';

export type TuiShareQr = { url:string; lines:string[]; width:number; height:number };

/** Keep the original fragment bytes: serializing URL can alter an encrypted share key. */
export function validTuiShareUrl(url:string, origin:string, target:'chat'|'embed'|'public'):boolean {
  // eslint-disable-next-line no-control-regex -- Never let a share URL inject terminal controls.
  if (!url || url.length>8192 || /[\s\x00-\x1f\x7f]/.test(url)) return false;
  try {
    const parsed=new URL(url), site=new URL(origin);
    if (!['https:','http:'].includes(parsed.protocol) || parsed.origin!==site.origin || parsed.username || parsed.password) return false;
    if (target==='public') return /^\/example\/[^/]+$/.test(parsed.pathname) && !parsed.hash;
    return new RegExp(`^/share/${target}/[^/]+$`).test(parsed.pathname) && /^#key=.+/.test(parsed.hash);
  } catch { return false; }
}

export function createTuiShareQr(url:string,origin:string,target:'chat'|'embed'|'public'):TuiShareQr|null {
  if (!validTuiShareUrl(url,origin,target)) return null;
  let printed='';
  try {qrcode.generate(url,{small:true},value=>{printed=value;});}
  catch {return null;}
  const compact=printed.replace(/\n$/,'').split('\n');
  const compactWidth=cells(compact[0]??''),size=compactWidth-2;
  if (size<21 || compact.length<11 || compact.some(line=>cells(line)!==compactWidth || /[^ ▄▀█]/u.test(line))) return null;
  // qrcode-terminal's compact mode has only a one-module border. Decode its
  // half blocks and add the QR standard's four light modules on every side.
  const dark=(r:number,c:number):boolean=>{
    const glyph=compact[1+Math.floor(r/2)]?.[1+c];
    return r%2===0?glyph===' '||glyph==='▄':glyph===' '||glyph==='▀';
  };
  const width=size+8;
  const pixel=(r:number,c:number)=>r>=4&&c>=4&&r<size+4&&c<size+4?dark(r-4,c-4):false;
  const lines:string[]=[];
  for(let r=0;r<width;r+=2){
    let line='';
    for(let c=0;c<width;c++){
      const top=pixel(r,c),bottom=r+1<width&&pixel(r+1,c);
      line+=top?(bottom?' ':'▄'):(bottom?'▀':'█');
    }
    lines.push(line);
  }
  return {url,lines,width,height:lines.length};
}
