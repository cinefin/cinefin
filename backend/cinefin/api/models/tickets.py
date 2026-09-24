"""Ticketing models: printed-ticket history and reusable ticket designs."""

from django.db import models, transaction


class TicketDesign(models.Model):
    """Named ticket layout: an ordered list of styled elements. Exactly one is
    the default, used when a programme has no ticket_design override."""

    name = models.CharField(max_length=120)
    is_default = models.BooleanField(default=False, db_index=True)
    elements = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name}{' (default)' if self.is_default else ''}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Keep exactly one default: demote any others once this becomes it.
        if self.is_default:
            TicketDesign.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)

    @classmethod
    def get_default(cls) -> "TicketDesign":
        """The default design, seeding a 'Standard' one on first use."""
        design = cls.objects.filter(is_default=True).order_by("id").first()
        if design:
            return design
        design = cls.objects.order_by("id").first()
        if design:
            design.is_default = True
            design.save()
            return design
        from cinefin.api.services.ticket_service import DEFAULT_DESIGN_ELEMENTS

        return cls.objects.create(name="Standard", is_default=True, elements=list(DEFAULT_DESIGN_ELEMENTS))


class TicketIssue(models.Model):
    # "movie" is legacy: per-feature printing was removed (tickets admit to a
    # whole programme now), but old history rows keep the kind for reprints.
    KIND_MOVIE = "movie"
    KIND_PROGRAMME = "programme"
    KIND_CUSTOM = "custom"
    KIND_CHOICES = [
        (KIND_MOVIE, "Movie"),
        (KIND_PROGRAMME, "Programme"),
        (KIND_CUSTOM, "Custom"),
    ]

    programme = models.ForeignKey(
        "Programme", on_delete=models.SET_NULL, null=True, blank=True, related_name="ticket_issues"
    )
    movie = models.ForeignKey("Movie", on_delete=models.SET_NULL, null=True, blank=True, related_name="ticket_issues")
    schedule = models.ForeignKey(
        "ProgrammeSchedule", on_delete=models.SET_NULL, null=True, blank=True, related_name="ticket_issues"
    )
    seat = models.CharField(max_length=10, blank=True, default="")
    ticket_number = models.PositiveIntegerField(db_index=True, help_text="Global running ticket counter")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    # Snapshot of what the ticket said, so history survives deletions.
    title = models.CharField(max_length=500, blank=True, default="")
    printed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-printed_at", "-id"]

    def __str__(self):
        return f"Ticket #{self.ticket_number} ({self.kind}) {self.title}".strip()

    @classmethod
    def issue(cls, **fields) -> "TicketIssue":
        # max()+1 in a transaction: SQLite serialises writers, so two concurrent
        # issues can't both read the same max and commit.
        with transaction.atomic():
            current = cls.objects.aggregate(n=models.Max("ticket_number"))["n"] or 0
            return cls.objects.create(ticket_number=current + 1, **fields)
