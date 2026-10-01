document.addEventListener('DOMContentLoaded', function () {
    const provider = document.getElementById('id_provider');
    const allTypes = document.getElementById('id_all_request_types');
    const typeBoxes = Array.from(document.querySelectorAll('input[name="request_types"]'));
    function updateFields() {
        if (provider) {
            document.querySelectorAll('.lead-telegram').forEach(function (element) {
                element.hidden = provider.value !== 'telegram';
            });
            document.querySelectorAll('.lead-email').forEach(function (element) {
                element.hidden = provider.value !== 'email';
            });
        }
    }
    function updateAllTypes() {
        if (!allTypes || !typeBoxes.length) return;
        const selected = typeBoxes.filter(function (box) { return box.checked; }).length;
        allTypes.checked = selected === typeBoxes.length;
        allTypes.indeterminate = selected > 0 && selected < typeBoxes.length;
    }
    if (provider) provider.addEventListener('change', updateFields);
    if (allTypes) {
        allTypes.addEventListener('change', function () {
            typeBoxes.forEach(function (box) { box.checked = allTypes.checked; });
            allTypes.indeterminate = false;
        });
        if (allTypes.checked) {
            typeBoxes.forEach(function (box) { box.checked = true; });
        }
    }
    typeBoxes.forEach(function (box) { box.addEventListener('change', updateAllTypes); });
    updateAllTypes();
    updateFields();
});
