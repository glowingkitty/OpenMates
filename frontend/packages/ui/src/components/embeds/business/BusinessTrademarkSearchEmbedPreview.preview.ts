/** Public ExampleTrademarks-style display fixtures; they are not live availability checks. */
export const trademarkData = {
  app_id: 'business', skill_id: 'search_trademarks', status: 'finished', success: true,
  query: 'ADIDAS', regions: ['US', 'DE'], provider: 'ExampleTrademarks', result_count: 1,
  nice_classes: [], status_filter: 'active', match: 'exact', partial: true,
  limitation: 'Preliminary search only. No matches do not establish legal availability.',
  coverage: [
    {query:'ADIDAS',region:'US',status:'searched',total_matches:20,returned_count:1,more_results:true,checked_at:'2026-10-11T11:25:40Z',source_url:'https://example.com/fixture'},
    {query:'ADIDAS',region:'DE',status:'unsupported',message:'German national coverage requires a manual register check.',source_url:'https://register.dpma.de/DPMAregister/marke/uebersicht'},
  ],
  matches: [{query:'ADIDAS',mark:'ADIDAS',region:'US',provider:'ExampleTrademarks',application_number:'72318279',registration_number:'0883592',owners:['adidas AG'],nice_classes:[18],goods_services:['Tote bags.'],status:'registered',status_description:'REGISTERED AND RENEWED',active:true,registered:true,source_url:'https://example.com/fixture'}],
};
export const emptyData = {...trademarkData,query:'Fictional candidate',regions:['US'],partial:false,result_count:0,matches:[],coverage:[{...trademarkData.coverage[0],query:'Fictional candidate',total_matches:0,returned_count:0,more_results:false}]};
export const errorData = {...trademarkData,status:'error',success:false,result_count:0,matches:[],error:'ExampleTrademarks search is currently unavailable.',coverage:[{query:'ADIDAS',region:'US',status:'error',message:'ExampleTrademarks search is currently unavailable.',source_url:'https://example.com/fixture'}]};
const props = {id:'preview-trademark-search',data:trademarkData,status:'finished' as const,presentationOnly:true,onFullscreen:()=>{}};
export default props;
export const variants = {
  processing: {...props,data:{query:'ADIDAS'},status:'processing' as const},
  error: {...props,data:errorData,status:'error' as const},
  cancelled: {...props,data:{query:'ADIDAS',status:'cancelled'},status:'cancelled' as const},
  empty: {...props,data:emptyData},
  mobile: {...props,isMobile:true},
  long: {...props,data:{...trademarkData,query:'A long candidate name with several words to verify narrow preview wrapping and accurate regional coverage'}},
};
