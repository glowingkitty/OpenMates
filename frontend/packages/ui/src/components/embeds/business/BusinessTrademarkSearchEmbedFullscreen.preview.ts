import {trademarkData,emptyData,errorData} from './BusinessTrademarkSearchEmbedPreview.preview';
const saved = (value: Record<string,unknown>) => ({app_id:'business',skill_id:'search_trademarks',status:'finished',result_count:1,results:[value]});
const props = {data:{decodedContent:saved(trademarkData)},onClose:()=>{}};
export default props;
export const variants = {
  missingData: { ...props, data: { decodedContent: saved({ ...trademarkData, matches: [{ mark: 'Example mark', status: 'unknown' }] }) } },
  direct: {...props,data:{decodedContent:trademarkData}},
  empty: {...props,data:{decodedContent:saved(emptyData)}},
  error: {...props,data:{decodedContent:saved(errorData)}},
  filters: {...props,data:{decodedContent:saved({...trademarkData,nice_classes:'9|42',match:'similar',status_filter:'all'})}},
  unsafeLink: {...props,data:{decodedContent:saved({...trademarkData,matches:[{...trademarkData.matches[0],source_url:'https://example.com/fixture'}]})}},
  long: {...props,data:{decodedContent:saved({...trademarkData,matches:[{...trademarkData.matches[0],mark:'A long trademark name to verify responsive wrapping on a narrow phone screen',owners:['An owner with a long legal company name'],goods_services:['A long goods and services description '.repeat(35)]}]})}},
};
