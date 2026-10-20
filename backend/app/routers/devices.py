import hmac

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from app.config import settings
from app.db.mongo import get_db
from app.deps import require_teacher
from app.models.schemas import Calibration as CalibrationBody, DeviceRegister
from app.services import crypto

router = APIRouter(prefix="/api/devices", tags=["Devices"])


@router.post("/register", status_code=201)
async def register_device(payload: DeviceRegister, db=Depends(get_db)):
    """Enrol a student's device key. Proof of possession: signature over register:{id}:{model}.
    An existing student_id can't be overwritten (anti-hijack); a teacher must delete it first.
    If the server sets ENROL_CODE, the phone must also present the class code (constant-time comparison)."""
    if settings.ENROL_CODE and not hmac.compare_digest((payload.enrol_code or "").encode(), settings.ENROL_CODE.encode()):
        raise HTTPException(status_code=403, detail="Wrong or missing class code.")
    if not crypto.verify(payload.public_key, crypto.register_message(payload.student_id, payload.model), payload.signature):
        raise HTTPException(status_code=400, detail="Invalid key or signature.")
    device_id = crypto.device_id_of(payload.public_key)
    other = await db.students.find_one({"$or": [{"device_id": device_id}] + ([{"install_id": payload.install_id}] if payload.install_id else [])},
                                       {"_id": 0, "student_id": 1})
    if other and other["student_id"] != payload.student_id:   # one phone, one student
        raise HTTPException(status_code=409, detail="This phone is already registered to another student. Ask your teacher to reset it.")
    doc = {"student_id": payload.student_id, "name": payload.name, "model": payload.model,
           "public_key": payload.public_key, "device_id": device_id}
    if payload.install_id:
        doc["install_id"] = payload.install_id
    if payload.platform:
        doc["platform"] = payload.platform
    try:
        await db.students.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Student already enrolled; ask the teacher to reset the device.")
    return {"status": "enrolled", "student_id": payload.student_id}


@router.get("", dependencies=[Depends(require_teacher)])
async def list_students(db=Depends(get_db)):
    return await db.students.find({}, {"_id": 0, "public_key": 0}).sort("student_id", 1).to_list(length=2000)


@router.delete("/{student_id}", dependencies=[Depends(require_teacher)])
async def reset_device(student_id: str, db=Depends(get_db)):
    res = await db.students.delete_one({"student_id": student_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Unknown student.")
    return {"status": "reset", "student_id": student_id}


@router.put("/calibration", dependencies=[Depends(require_teacher)], tags=["Calibration"])
async def set_calibration(payload: CalibrationBody, db=Depends(get_db)):
    await db.device_calibration.update_one(
        {"model": payload.model}, {"$set": {"model": payload.model, "rssi_offset_db": payload.rssi_offset_db}}, upsert=True)
    return {"status": "ok", "model": payload.model, "rssi_offset_db": payload.rssi_offset_db}


@router.get("/calibration", dependencies=[Depends(require_teacher)], tags=["Calibration"])
async def get_calibration(db=Depends(get_db)):
    return await db.device_calibration.find({}, {"_id": 0}).sort("model", 1).to_list(length=500)
