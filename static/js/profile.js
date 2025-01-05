document.querySelectorAll('.nav-link').forEach(item => {
    item.addEventListener('click', () => {
        let target = item.getAttribute('data-bs-target');
        if (target === 'settings') {
            getSettings();
        }
        document.querySelectorAll('.tab-content').forEach(content => {
            if (content.id === target) {
                content.classList.remove('d-none');
            } else {
                content.classList.add('d-none');
            }
        });
        document.querySelector('.nav-link.active').classList.remove('active');
        item.classList.add('active');
    });
});

function updateSetting(setting, value) {
    fetch(`/api/settings/`, {
        method: 'PUT',
        body: JSON.stringify({
            [setting]: value
        }),
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    }).then(response => {
        if (!response.ok) {
            console.error('Failed to update setting');
        }
    });
}

function getSettings() {
    fetch('/api/settings/').then(response => {
        if (response.ok) {
            return response.json();
        } else {
            console.error('Failed to fetch settings');
        }
    }).then(data => {
        for (let setting in data) {
            const inputElement = document.querySelector(`[name="${setting}"]`);
            if (inputElement) {
                if (inputElement.type === 'checkbox') {
                    inputElement.checked = data[setting];
                } else {
                    inputElement.value = data[setting];
                }
            }
        }
    });
}

document.querySelectorAll('.settings-input').forEach(input => {
    input.addEventListener('change', e => {
        const target = e.target;
        if (target.type === 'checkbox') {
            updateSetting(target.name, target.checked);
        } else if (target.type === 'number' || target.type === 'range') {
            if (target.value < parseInt(target.min, 10)) {
                target.value = target.min;
            }
            updateSetting(target.name, parseInt(target.value, 10));
        } else {
            updateSetting(target.name, target.value);
        }
    });
});