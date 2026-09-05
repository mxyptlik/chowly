"""Staff identity services independent of HTTP transport."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.security import hash_opaque_token, hash_password, issue_invitation_token, verify_password
from app.models import (
    AuditEvent,
    InvitationStatus,
    Location,
    StaffAccount,
    StaffLocationAssignment,
    StaffRole,
    StaffRoleAssignment,
)


class AuthenticationFailed(ValueError):
    pass


class InvitationInvalid(ValueError):
    pass


class InvitationExpired(InvitationInvalid):
    pass


class InvitationConflict(ValueError):
    pass


class StaffAssignmentInvalid(ValueError):
    pass


class StaffAssignmentNotFound(StaffAssignmentInvalid):
    pass


@dataclass(frozen=True, slots=True)
class CurrentStaff:
    account: StaffAccount
    tenant_id: str | None
    roles: frozenset[StaffRole]
    location_ids: frozenset[str]
    active_location_id: str | None
    locations: tuple[Location, ...]

    @property
    def staff_id(self) -> str:
        return self.account.id

    @property
    def is_platform_admin(self) -> bool:
        return self.account.is_platform_admin or StaffRole.PLATFORM_ADMIN in self.roles

    def has_any_role(self, roles: set[StaffRole] | frozenset[StaffRole]) -> bool:
        return bool(self.roles.intersection(roles))


def normalized_email(email: str) -> str:
    return email.strip().lower()


def _staff_query():
    return select(StaffAccount).options(
        selectinload(StaffAccount.role_assignments),
        selectinload(StaffAccount.location_assignments),
    )


def authenticate_staff(db: Session, email: str, password: str) -> StaffAccount:
    account = db.scalar(_staff_query().where(StaffAccount.email == normalized_email(email)))
    accepted = account and account.invitation_status == InvitationStatus.ACCEPTED
    if not accepted or not account.is_active or not verify_password(password, account.password_hash):
        raise AuthenticationFailed("Invalid email or password.")
    return account


def current_staff_from_account(
    db: Session,
    account: StaffAccount,
    *,
    active_location_id: str | None = None,
) -> CurrentStaff:
    roles = {assignment.role for assignment in account.role_assignments}
    if account.is_platform_admin:
        roles.add(StaffRole.PLATFORM_ADMIN)
    location_ids = {assignment.location_id for assignment in account.location_assignments}
    locations = tuple(
        db.scalars(
            select(Location)
            .where(Location.id.in_(location_ids))
            .order_by(Location.name, Location.id)
        )
    ) if location_ids else ()
    chosen_location = active_location_id if active_location_id in location_ids else None
    if chosen_location is None and locations:
        chosen_location = locations[0].id
    return CurrentStaff(
        account=account,
        tenant_id=account.tenant_id,
        roles=frozenset(roles),
        location_ids=frozenset(location_ids),
        active_location_id=chosen_location,
        locations=locations,
    )


def load_current_staff(
    db: Session,
    staff_id: str,
    *,
    expected_tenant_id: str | None,
    active_location_id: str | None,
) -> CurrentStaff:
    account = db.scalar(_staff_query().where(StaffAccount.id == staff_id))
    if (
        not account
        or not account.is_active
        or account.invitation_status != InvitationStatus.ACCEPTED
        or account.tenant_id != expected_tenant_id
    ):
        raise AuthenticationFailed("Invalid staff session.")
    return current_staff_from_account(db, account, active_location_id=active_location_id)


def create_invitation(
    db: Session,
    *,
    inviter: CurrentStaff,
    name: str,
    email: str,
    roles: list[StaffRole],
    location_ids: list[str],
    ttl: timedelta,
    now: datetime | None = None,
) -> tuple[StaffAccount, str]:
    if inviter.tenant_id is None:
        raise InvitationInvalid("A restaurant tenant is required for staff invitations.")
    clean_email = normalized_email(email)
    if db.scalar(select(StaffAccount.id).where(StaffAccount.email == clean_email)):
        raise InvitationConflict("A staff account already exists for this email.")

    requested_roles = set(roles)
    if StaffRole.PLATFORM_ADMIN in requested_roles:
        raise InvitationInvalid("Restaurant staff invitations cannot grant platform administration.")
    if StaffRole.TENANT_OWNER not in inviter.roles:
        manager_grants = {StaffRole.WAITER, StaffRole.CHEF, StaffRole.BARTENDER}
        if StaffRole.MANAGER not in inviter.roles or not requested_roles.issubset(manager_grants):
            raise InvitationInvalid("This staff account cannot grant the requested roles.")
    requested_locations = set(location_ids)
    if not requested_locations.issubset(inviter.location_ids):
        raise InvitationInvalid("Invitations may use only explicitly assigned locations.")
    owned_location_ids = set(
        db.scalars(
            select(Location.id).where(
                Location.tenant_id == inviter.tenant_id,
                Location.id.in_(requested_locations),
                Location.is_active.is_(True),
            )
        )
    )
    if owned_location_ids != requested_locations:
        raise InvitationInvalid("One or more locations are unavailable.")

    raw_token, token_hash = issue_invitation_token()
    issued_at = now or datetime.now(UTC)
    account = StaffAccount(
        tenant_id=inviter.tenant_id,
        name=name.strip(),
        email=clean_email,
        invitation_status=InvitationStatus.PENDING,
        invitation_token_hash=token_hash,
        invitation_expires_at=issued_at + ttl,
        invited_by_id=inviter.staff_id,
        is_active=True,
    )
    db.add(account)
    db.flush()
    db.add_all(
        StaffRoleAssignment(
            tenant_id=inviter.tenant_id,
            staff_id=account.id,
            role=role,
            granted_by_id=inviter.staff_id,
        )
        for role in sorted(requested_roles, key=lambda item: item.value)
    )
    db.add_all(
        StaffLocationAssignment(
            tenant_id=inviter.tenant_id,
            location_id=location_id,
            staff_id=account.id,
            assigned_by_id=inviter.staff_id,
        )
        for location_id in sorted(requested_locations)
    )
    db.commit()
    return account, raw_token


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def accept_invitation(
    db: Session,
    *,
    raw_token: str,
    password: str,
    now: datetime | None = None,
) -> StaffAccount:
    account = db.scalar(
        _staff_query().where(StaffAccount.invitation_token_hash == hash_opaque_token(raw_token))
    )
    if not account or account.invitation_status != InvitationStatus.PENDING:
        raise InvitationInvalid("This invitation is invalid or has already been used.")
    current = now or datetime.now(UTC)
    if not account.invitation_expires_at or _as_utc(account.invitation_expires_at) <= current:
        account.invitation_status = InvitationStatus.EXPIRED
        account.invitation_token_hash = None
        db.commit()
        raise InvitationExpired("This invitation has expired.")
    account.password_hash = hash_password(password)
    account.invitation_status = InvitationStatus.ACCEPTED
    account.accepted_at = current
    account.invitation_token_hash = None
    account.invitation_expires_at = None
    db.commit()
    return account


def tenant_staff_accounts(db: Session, *, tenant_id: str) -> list[StaffAccount]:
    """Return only members of the caller's tenant, with grants ready for output."""
    return list(
        db.scalars(
            _staff_query()
            .where(StaffAccount.tenant_id == tenant_id)
            .order_by(StaffAccount.name, StaffAccount.id)
        )
    )


def update_staff_assignments(
    db: Session,
    *,
    actor: CurrentStaff,
    target_staff_id: str,
    roles: list[StaffRole],
    location_ids: list[str],
) -> StaffAccount:
    """Replace one tenant member's grants without allowing privilege escape/lockout.

    Only a tenant owner may call this service.  The router owns the HTTP policy;
    keeping the tenant and last-owner checks here makes the same rules available
    to future non-HTTP administration workflows.
    """
    if actor.tenant_id is None or StaffRole.TENANT_OWNER not in actor.roles:
        raise StaffAssignmentInvalid("Tenant-owner access is required.")

    requested_roles = set(roles)
    requested_locations = set(location_ids)
    if not requested_roles or not requested_locations:
        raise StaffAssignmentInvalid("At least one role and location assignment is required.")
    if StaffRole.PLATFORM_ADMIN in requested_roles:
        raise StaffAssignmentInvalid("Tenant staff assignments cannot grant platform administration.")

    target = db.scalar(
        _staff_query()
        .where(StaffAccount.id == target_staff_id, StaffAccount.tenant_id == actor.tenant_id)
        .with_for_update()
    )
    if target is None:
        raise StaffAssignmentNotFound("Staff member not found.")
    if target.is_platform_admin:
        raise StaffAssignmentInvalid("Platform accounts cannot be managed from a tenant.")

    valid_location_ids = set(
        db.scalars(
            select(Location.id).where(
                Location.tenant_id == actor.tenant_id,
                Location.id.in_(requested_locations),
                Location.is_active.is_(True),
            )
        )
    )
    if valid_location_ids != requested_locations:
        raise StaffAssignmentInvalid("One or more locations are unavailable.")

    current_roles = {assignment.role for assignment in target.role_assignments}
    removes_owner = StaffRole.TENANT_OWNER in current_roles and StaffRole.TENANT_OWNER not in requested_roles
    if removes_owner:
        # Lock all owner rows in the tenant so two concurrent demotions cannot
        # both observe a different owner and leave the tenant unmanaged.
        owner_assignments = list(
            db.scalars(
                select(StaffRoleAssignment)
                .where(
                    StaffRoleAssignment.tenant_id == actor.tenant_id,
                    StaffRoleAssignment.role == StaffRole.TENANT_OWNER,
                )
                .with_for_update()
            )
        )
        if len(owner_assignments) <= 1:
            raise StaffAssignmentInvalid("A tenant must retain at least one tenant owner.")

    if target.id == actor.staff_id:
        if StaffRole.TENANT_OWNER not in requested_roles:
            raise StaffAssignmentInvalid("You cannot remove your own tenant-owner role.")
        if not requested_locations:
            raise StaffAssignmentInvalid("You cannot remove your own final location assignment.")

    before_data = {
        "roles": sorted(role.value for role in current_roles),
        "location_ids": sorted(assignment.location_id for assignment in target.location_assignments),
    }
    target.role_assignments.clear()
    target.location_assignments.clear()
    db.flush()
    db.add_all(
        StaffRoleAssignment(
            tenant_id=actor.tenant_id,
            staff_id=target.id,
            role=role,
            granted_by_id=actor.staff_id,
        )
        for role in sorted(requested_roles, key=lambda item: item.value)
    )
    db.add_all(
        StaffLocationAssignment(
            tenant_id=actor.tenant_id,
            staff_id=target.id,
            location_id=location_id,
            assigned_by_id=actor.staff_id,
        )
        for location_id in sorted(requested_locations)
    )
    # Audit events require a tenant-location scope.  An owner has at least one
    # assignment by contract, and this is an administrative action rather than
    # a customer/order event, so its active location is the correct scope.
    audit_location_id = actor.active_location_id or sorted(actor.location_ids)[0]
    db.add(
        AuditEvent(
            tenant_id=actor.tenant_id,
            location_id=audit_location_id,
            actor_id=actor.staff_id,
            event_type="staff.assignments.updated",
            subject_type="staff_account",
            subject_id=target.id,
            detail="Tenant owner replaced staff role and location assignments.",
            before_data=before_data,
            after_data={
                "roles": sorted(role.value for role in requested_roles),
                "location_ids": sorted(requested_locations),
            },
        )
    )
    db.commit()
    # The target was loaded with collections before the replacement.  Expire it
    # before the response query so SQLAlchemy does not return those now-stale
    # in-memory empty collections instead of the newly persisted grants.
    db.expire(target)
    return db.scalar(_staff_query().where(StaffAccount.id == target.id)) or target
