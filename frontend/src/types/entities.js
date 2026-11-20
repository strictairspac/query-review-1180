/** @typedef {{id:number,name:string,description:string,original_sql:string}} Sample */
/** @typedef {{id:number,currency:string,rate_date:string,rate:string}} FxRate */
/** @typedef {{currency:string,date:string,rate:string}} LockedRate */
/** @typedef {{id:number,name:string,sample_id:number,candidate_sql:string,status:string,fx_snapshot:LockedRate[],fx_missing:{currency:string,date:string}[]}} Batch */
/** @typedef {{id:number,batch_id:number,result:Object}} Evidence */
export const entityNames={sample:'SQL 样本',batch:'复核批次',evidence:'执行证据',fxRate:'折算汇率'};
