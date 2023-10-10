from django import forms
from pict.models import Pict


class PictAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].initial = self.instance + 1  # автоподставление последней записи+1 добавить изображение

    class Meta:
        model = Pict
        fields = ['name', ]
