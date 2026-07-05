"""
farm/worker_views.py
────────────────────
Views for Worker management — list, add, edit, delete, salary payment.
Follows the same login_required + user-scoping pattern as farm/views.py.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum, Count
from django.utils import timezone
from datetime import date

from .models import Worker, SalaryPayment, FarmProfile, Expense
from .worker_forms import WorkerForm, SalaryPaymentForm


def _get_farm(user):
    """Helper — get or raise 404 for the user's FarmProfile."""
    try:
        return user.farm_profile
    except FarmProfile.DoesNotExist:
        return None


# ── Worker List ───────────────────────────────────────────────────────────────

@login_required
def worker_list(request):
    farm = _get_farm(request.user)
    if not farm:
        messages.warning(request, "Please complete onboarding first.")
        return redirect("farm:onboarding_step1")

    workers = Worker.objects.filter(farm=farm).prefetch_related("assigned_ponds")

    # Summary stats
    total_workers  = workers.filter(status="active").count()
    total_salary   = workers.filter(status="active").aggregate(
        t=Sum("monthly_salary"))["t"] or 0

    # Pending salaries this month
    this_month = date.today().replace(day=1)
    pending_count = SalaryPayment.objects.filter(
        worker__farm=farm,
        month=this_month,
        status="pending"
    ).count()

    context = {
        "workers":       workers,
        "total_workers": total_workers,
        "total_salary":  total_salary,
        "pending_count": pending_count,
        "this_month":    this_month,
    }
    return render(request, "farm/worker_list.html", context)


# ── Add Worker ────────────────────────────────────────────────────────────────

@login_required
def worker_create(request):
    farm = _get_farm(request.user)
    if not farm:
        return redirect("farm:onboarding_step1")

    if request.method == "POST":
        form = WorkerForm(request.POST, user=request.user)
        if form.is_valid():
            worker      = form.save(commit=False)
            worker.farm = farm
            worker.save()
            form.save_m2m()  # save ManyToMany (assigned_ponds)
            messages.success(request, f"✅ {worker.name} successfully added.")
            return redirect("farm:worker_list")
    else:
        form = WorkerForm(user=request.user)

    return render(request, "farm/worker_form.html", {
        "form":  form,
        "title": "Add Worker",
        "btn":   "Save Worker",
    })


# ── Edit Worker ───────────────────────────────────────────────────────────────

@login_required
def worker_update(request, pk):
    farm   = _get_farm(request.user)
    worker = get_object_or_404(Worker, pk=pk, farm=farm)

    if request.method == "POST":
        form = WorkerForm(request.POST, instance=worker, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, f"✅ {worker.name}-Update successful.")
            return redirect("farm:worker_list")
    else:
        form = WorkerForm(instance=worker, user=request.user)

    return render(request, "farm/worker_form.html", {
        "form":   form,
        "title":  f"Edit: {worker.name}",
        "btn":    "Update Worker",
        "worker": worker,
    })


# ── Delete Worker ─────────────────────────────────────────────────────────────

@login_required
def worker_delete(request, pk):
    farm   = _get_farm(request.user)
    worker = get_object_or_404(Worker, pk=pk, farm=farm)

    if request.method == "POST":
        name = worker.name
        worker.delete()
        messages.success(request, f"🗑️ {name} successfully deleted.")
        return redirect("farm:worker_list")

    return render(request, "farm/worker_confirm_delete.html", {"worker": worker})


# ── Worker Detail ─────────────────────────────────────────────────────────────

@login_required
def worker_detail(request, pk):
    farm   = _get_farm(request.user)
    worker = get_object_or_404(Worker, pk=pk, farm=farm)

    payments = SalaryPayment.objects.filter(worker=worker).order_by("-month")
    total_paid = payments.filter(status="paid").aggregate(
        t=Sum("amount_paid"))["t"] or 0

    context = {
        "worker":     worker,
        "payments":   payments,
        "total_paid": total_paid,
    }
    return render(request, "farm/worker_detail.html", context)


# ── Salary Payment ────────────────────────────────────────────────────────────

@login_required
def salary_pay(request, pk):
    farm   = _get_farm(request.user)
    worker = get_object_or_404(Worker, pk=pk, farm=farm)

    # Pre-fill current month and full salary
    initial = {
        "worker":      worker,
        "month":       date.today().replace(day=1),
        "amount_paid": worker.monthly_salary,
        "status":      "paid",
        "paid_on":     date.today(),
    }

    if request.method == "POST":
        form = SalaryPaymentForm(request.POST, user=request.user)
        if form.is_valid():
            payment = form.save()

            # Auto-create an Expense entry so finance section stays in sync
            Expense.objects.create(
                pond        = None,
                date        = payment.paid_on or date.today(),
                category    = "labour",
                amount      = payment.amount_paid,
                description = f"Salary: {worker.name} — {payment.month.strftime('%B %Y')}",
            )
            messages.success(
                request,
                f"✅ {worker.name}-s salary record for {payment.month.strftime('%B %Y')} has been added."
            )
            return redirect("farm:worker_detail", pk=pk)
    else:
        form = SalaryPaymentForm(initial=initial, user=request.user)

    return render(request, "farm/salary_form.html", {
        "form":   form,
        "worker": worker,
    })


# ── Salary List (all workers, current month) ──────────────────────────────────

@login_required
def salary_list(request):
    farm       = _get_farm(request.user)
    this_month = date.today().replace(day=1)

    workers  = Worker.objects.filter(farm=farm, status="active")
    payments = SalaryPayment.objects.filter(
        worker__farm=farm,
        month=this_month
    ).select_related("worker")

    paid_ids = set(payments.filter(status="paid").values_list("worker_id", flat=True))

    # Build combined list
    salary_rows = []
    for w in workers:
        payment = payments.filter(worker=w).first()
        salary_rows.append({
            "worker":  w,
            "payment": payment,
            "is_paid": w.id in paid_ids,
        })

    total_payable = workers.aggregate(t=Sum("monthly_salary"))["t"] or 0
    total_paid    = payments.filter(status="paid").aggregate(
        t=Sum("amount_paid"))["t"] or 0

    context = {
        "salary_rows":   salary_rows,
        "this_month":    this_month,
        "total_payable": total_payable,
        "total_paid":    total_paid,
        "total_pending": total_payable - total_paid,
    }
    return render(request, "farm/salary_list.html", context)
