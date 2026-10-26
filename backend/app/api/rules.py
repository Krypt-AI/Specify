import uuid
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import ClassificationFeedback, ClassificationRule, Label, User
from app.schemas.rule import RuleConditions, RuleCreate, RuleOut, RuleSuggestion, RuleUpdate
from app.services.email_domains import FREE_MAIL_DOMAINS

router = APIRouter(prefix="/rules", tags=["rules"])

MIN_SENDER_CORRECTIONS = 2
MIN_DOMAIN_CORRECTIONS = 3


@router.get("", response_model=list[RuleOut])
def list_rules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(ClassificationRule).where(ClassificationRule.user_id == user.id).order_by(ClassificationRule.created_at)
    ).all()


@router.post("", response_model=RuleOut, status_code=201)
def create_rule(body: RuleCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check_label(db, user, body.target_label_id)
    rule = ClassificationRule(user_id=user.id, **body.model_dump())
    db.add(rule)
    db.commit()
    return rule


@router.patch("/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: uuid.UUID, body: RuleUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rule = _owned_rule(db, user, rule_id)
    changes = body.model_dump(exclude_unset=True)
    if "target_label_id" in changes:
        _check_label(db, user, body.target_label_id)
    for field, value in changes.items():
        setattr(rule, field, value)
    db.commit()
    return rule


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    db.delete(_owned_rule(db, user, rule_id))
    db.commit()


@router.get("/suggestions", response_model=list[RuleSuggestion])
def rule_suggestions(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[RuleSuggestion]:
    """Rules proposed from repeated corrections. Nothing changes until the user accepts one."""
    feedback = db.scalars(
        select(ClassificationFeedback)
        .where(ClassificationFeedback.user_id == user.id)
        .order_by(ClassificationFeedback.created_at.desc())
        .limit(500)
    ).all()
    rules = db.scalars(select(ClassificationRule).where(ClassificationRule.user_id == user.id)).all()
    covered_senders = {e for r in rules for e in r.conditions.get("sender_emails", [])}
    covered_domains = {d for r in rules for d in r.conditions.get("sender_domains", [])}
    labels = {label.id: label for label in db.scalars(select(Label).where(Label.user_id == user.id))}

    suggestions = []
    by_sender = Counter((f.sender_email, f.corrected_group, f.corrected_label_id) for f in feedback)
    for (sender, group, label_id), count in by_sender.most_common():
        if count >= MIN_SENDER_CORRECTIONS and sender not in covered_senders:
            covered_senders.add(sender)
            label_name = labels[label_id].name if label_id in labels else None
            suggestions.append(
                RuleSuggestion(
                    reason=f"You corrected {count} emails from {sender} the same way.",
                    rule=RuleCreate(
                        name=f"Emails from {sender}",
                        conditions=RuleConditions(sender_emails=[sender]),
                        target_group=group,
                        target_label_id=label_id if label_name else None,
                    ),
                )
            )
    by_domain = Counter(
        (f.sender_domain, f.corrected_group) for f in feedback if f.sender_domain not in FREE_MAIL_DOMAINS
    )
    for (domain, group), count in by_domain.most_common():
        if count >= MIN_DOMAIN_CORRECTIONS and domain not in covered_domains:
            covered_domains.add(domain)
            suggestions.append(
                RuleSuggestion(
                    reason=f"You moved {count} emails from {domain} to {group}.",
                    rule=RuleCreate(
                        name=f"Emails from {domain}",
                        conditions=RuleConditions(sender_domains=[domain]),
                        target_group=group,
                    ),
                )
            )
    return suggestions


def _owned_rule(db: Session, user: User, rule_id: uuid.UUID) -> ClassificationRule:
    rule = db.get(ClassificationRule, rule_id)
    if rule is None or rule.user_id != user.id:
        raise HTTPException(404, "Rule not found")
    return rule


def _check_label(db: Session, user: User, label_id: uuid.UUID | None) -> None:
    if label_id is None:
        return
    label = db.get(Label, label_id)
    if label is None or label.user_id != user.id or label.system_key:
        raise HTTPException(404, "Label not found")
