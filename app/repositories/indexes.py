from pymongo import ASCENDING, DESCENDING


async def create_indexes(database) -> dict[str, list[str]]:
    created: dict[str, list[str]] = {
        "companies": [],
        "users": [],
        "products": [],
        "customer_product_assignments": [],
        "access_requests": [],
        "sessions": [],
        "invitations": [],
    }

    idx = await database.companies.create_index(
        [("name", ASCENDING)],
        name="company_name",
    )
    created["companies"].append(idx)

    idx = await database.users.create_index(
        [("email", ASCENDING)],
        unique=True,
        name="unique_user_email",
    )
    created["users"].append(idx)
    idx = await database.users.create_index(
        [("company_id", ASCENDING), ("role", ASCENDING)],
        name="users_by_company_and_role",
    )
    created["users"].append(idx)

    idx = await database.products.create_index(
        [("status", ASCENDING), ("name", ASCENDING)],
        name="products_by_status_and_name",
    )
    created["products"].append(idx)
    idx = await database.products.create_index(
        [("applications", ASCENDING)],
        name="products_by_application",
    )
    created["products"].append(idx)
    idx = await database.products.create_index(
        [("catalog_key", ASCENDING)],
        unique=True,
        sparse=True,
        name="unique_product_catalog_key",
    )
    created["products"].append(idx)

    idx = await database.customer_product_assignments.create_index(
        [("company_id", ASCENDING), ("product_id", ASCENDING)],
        unique=True,
        name="unique_company_product_assignment",
    )
    created["customer_product_assignments"].append(idx)
    idx = await database.customer_product_assignments.create_index(
        [("company_id", ASCENDING), ("is_active", ASCENDING)],
        name="active_assignments_by_company",
    )
    created["customer_product_assignments"].append(idx)

    idx = await database.access_requests.create_index(
        [("company_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)],
        name="access_requests_by_company_status",
    )
    created["access_requests"].append(idx)
    idx = await database.access_requests.create_index(
        [("status", ASCENDING), ("created_at", DESCENDING)],
        name="access_requests_by_status",
    )
    created["access_requests"].append(idx)
    idx = await database.access_requests.create_index(
        [("company_id", ASCENDING), ("product_id", ASCENDING), ("status", ASCENDING)],
        name="access_requests_by_company_product_status",
    )
    created["access_requests"].append(idx)


    idx = await database.sessions.create_index(
        [("session_token_hash", ASCENDING)],
        unique=True,
        name="unique_session_token_hash",
    )
    created["sessions"].append(idx)
    idx = await database.sessions.create_index(
        [("user_id", ASCENDING)],
        name="sessions_by_user_id",
    )
    created["sessions"].append(idx)
    idx = await database.sessions.create_index(
        [("expires_at", ASCENDING)],
        name="sessions_by_expires_at",
    )
    created["sessions"].append(idx)

    idx = await database.invitations.create_index(
        [("invitation_token_hash", ASCENDING)],
        unique=True,
        name="unique_invitation_token_hash",
    )
    created["invitations"].append(idx)
    idx = await database.invitations.create_index(
        [("company_id", ASCENDING), ("status", ASCENDING)],
        name="invitations_by_company_status",
    )
    created["invitations"].append(idx)
    idx = await database.invitations.create_index(
        [("email", ASCENDING), ("status", ASCENDING)],
        name="invitations_by_email_status",
    )
    created["invitations"].append(idx)

    created["conversations"] = []
    idx = await database.conversations.create_index(
        [("company_id", ASCENDING), ("user_id", ASCENDING), ("created_at", DESCENDING)],
        name="conversations_by_company_user_created",
    )
    created["conversations"].append(idx)
    idx = await database.conversations.create_index(
        [("status", ASCENDING)],
        name="conversations_by_status",
    )
    created["conversations"].append(idx)

    audit_col = getattr(database, "audit_logs", None)
    if audit_col is not None:
        created["audit_logs"] = []
        idx = await audit_col.create_index(
            [("created_at", DESCENDING)],
            name="audit_logs_by_created_at",
        )
        created["audit_logs"].append(idx)

    leads_col = getattr(database, "leads", None)
    if leads_col is not None:
        created["leads"] = []
        idx = await leads_col.create_index(
            [("company_id", ASCENDING), ("created_at", DESCENDING)],
            name="leads_by_company_created",
        )
        created["leads"].append(idx)
        idx = await leads_col.create_index(
            [("conversation_id", ASCENDING)],
            name="leads_by_conversation",
        )
        created["leads"].append(idx)
        idx = await leads_col.create_index(
            [("stage", ASCENDING), ("created_at", DESCENDING)],
            name="leads_by_stage_created",
        )
        created["leads"].append(idx)
        idx = await leads_col.create_index(
            [("created_at", DESCENDING)],
            name="leads_by_created_at",
        )
        created["leads"].append(idx)

    return created



