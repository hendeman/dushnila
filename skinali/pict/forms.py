from django import forms
from pict.admin import PictAdmin


class PictAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].initial = 'name222'

    class Meta:
        model = PictAdmin


