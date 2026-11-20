from fastapi import APIRouter,Depends,Response
from ..config.database import get_db
from ..schemas.fx import RateInput
from ..services.auth import current_user,writer
from ..services.fx import list_rates,save_rate
router=APIRouter(prefix='/fx')
@router.get('/rates')
def rates(db=Depends(get_db),user=Depends(current_user)):return list_rates(db)
@router.post('/rates',status_code=201,responses={200:{'description':'该币种运输日已有汇率，保留首个入库值'}})
def record(data:RateInput,response:Response,db=Depends(get_db),user=Depends(writer)):
    result=save_rate(db,data,correct=False)
    if not result['created']:response.status_code=200
    return result
@router.put('/rates')
def correct(data:RateInput,db=Depends(get_db),user=Depends(writer)):return save_rate(db,data,correct=True)
