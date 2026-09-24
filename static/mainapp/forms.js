document.querySelectorAll('[data-password-toggle]').forEach((button) => {
    button.addEventListener('click', () => {
        const input = document.getElementById(button.dataset.target);
        const isVisible = input.type === 'text';

        input.type = isVisible ? 'password' : 'text';
        const label = isVisible ? button.dataset.showLabel : button.dataset.hideLabel;
        button.setAttribute('aria-label', label);
        button.setAttribute('title', label);
    });
});