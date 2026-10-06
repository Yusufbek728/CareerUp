document.querySelectorAll('.salary-range-sliders').forEach((container) => {
    const minRange = container.querySelector('[data-salary-min-range]');
    const maxRange = container.querySelector('[data-salary-max-range]');
    const minInput = document.getElementById('id_salary_min');
    const maxInput = document.getElementById('id_salary_max');

    if (!minRange || !maxRange || !minInput || !maxInput) {
        return;
    }

    const maxValue = Number(container.dataset.max) || 10000000;
    minRange.max = String(maxValue);
    maxRange.max = String(maxValue);

    const syncFromRanges = () => {
        if (Number(minRange.value) > Number(maxRange.value)) {
            minRange.value = maxRange.value;
        }
        minInput.value = minRange.value;
        maxInput.value = maxRange.value;
    };

    const syncFromInputs = () => {
        const minValue = Math.max(0, Math.min(maxValue, Number(minInput.value) || 0));
        const maxValueInput = Math.max(0, Math.min(maxValue, Number(maxInput.value) || maxValue));
        minRange.value = String(Math.min(minValue, maxValueInput));
        maxRange.value = String(Math.max(minValue, maxValueInput));
    };

    minRange.addEventListener('input', syncFromRanges);
    maxRange.addEventListener('input', syncFromRanges);
    minInput.addEventListener('input', syncFromInputs);
    maxInput.addEventListener('input', syncFromInputs);
    syncFromInputs();
});
