from django.shortcuts import render


def company_room(request):
    return render(request, 'chat/room.html')
