document.addEventListener('DOMContentLoaded', () => {
  const skinaliTypeField = document.querySelector('#id_skinali_type');
  const catalogImageField = document.querySelector('#id_catalog_image');
  const paintColorField = document.querySelector('#id_paint_color');

  if (!skinaliTypeField || !catalogImageField || !paintColorField) {
    return;
  }

  const fieldRow = (field) => (
    field.closest('.form-row') || field.closest('.fieldBox')
  );

  const clearField = (field) => {
    if (!field.value) {
      return;
    }
    field.value = '';
    field.dispatchEvent(new Event('change', { bubbles: true }));
  };

  const setFieldState = (field, visible, required = false) => {
    const row = fieldRow(field);
    if (row) {
      row.hidden = !visible;
    }
    field.disabled = !visible;
    field.required = visible && required;
    field.setAttribute('aria-required', String(visible && required));
    if (!visible) {
      clearField(field);
    }
  };

  const updateConditionalFields = () => {
    const selectedType = skinaliTypeField.value;
    const showCatalogImage = selectedType === 'print';
    const showPaintColor = selectedType === 'paint';

    setFieldState(catalogImageField, showCatalogImage);
    setFieldState(paintColorField, showPaintColor, showPaintColor);
  };

  skinaliTypeField.addEventListener('change', updateConditionalFields);
  updateConditionalFields();
});
