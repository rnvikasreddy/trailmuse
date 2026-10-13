from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme


def signup(request):
    next_url = request.POST.get("next") or request.GET.get("next") or "/"
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
        next_url = "/"
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect(next_url)
    else:
        form = UserCreationForm()
    return render(request, "registration/signup.html", {"form": form, "next": next_url})
