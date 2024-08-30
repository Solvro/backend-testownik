document.addEventListener('DOMContentLoaded', function() {
    answers = document.querySelectorAll('.answer');
    answers.forEach(function(answer) {
        answer.addEventListener('click', function() {
            answer.classList.toggle('is-info');
            answer.classList.toggle('is-soft');
        });
    });
});