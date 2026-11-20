import{api,post}from'./client.js';export const listRates=()=>api('/fx/rates');
export const recordRate=data=>post('/fx/rates',data);
export const correctRate=data=>api('/fx/rates',{method:'PUT',body:JSON.stringify(data)});
