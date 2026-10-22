from app.models.common import MongoModel, PyObjectId


class CustomerProductAssignment(MongoModel):
    company_id: PyObjectId
    product_id: PyObjectId
    assigned_by_user_id: PyObjectId
    is_active: bool = True
