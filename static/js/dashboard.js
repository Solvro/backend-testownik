let enableEdit = false;

document.addEventListener('DOMContentLoaded', () => {
    fetchQuestion();

    document.getElementById('check-answers-button').addEventListener('click', checkAnswers);
    document.getElementById('next-question-button').addEventListener('click', () => {
        fetchQuestion();
        document.getElementById('result').innerHTML = '';
        document.getElementById('check-answers-button').classList.remove('d-none');
        document.getElementById('next-question-button').classList.add('d-none');
    });
});

// Fetch a random question and display it
function fetchQuestion() {
    fetch('/api/random-question-for-user/')
        .then(async (response) => {
            if (!response.ok) {
                document.getElementById('pop-quiz').classList.add('d-none');
                document.getElementById('pop-quiz-not-available').classList.remove('d-none');
                return;
            }
            const data = await response.json();

            // Update question and quiz details
            document.getElementById('question').innerHTML = `${data.id}. ${data.question}`;
            document.getElementById('quiz-title').innerHTML = data.quiz_title;
            document.getElementById('quiz-title').href = `/quizzes/${data.quiz_id}/?question=${data.id}`;

            // Display answers
            const answers = document.getElementById('answers');
            answers.innerHTML = '';
            data.answers.forEach((answer) => {
                const answerElement = document.createElement('button');
                answerElement.className = 'btn btn-outline-secondary w-100 mb-2 answer';
                answerElement.innerHTML = answer.answer;
                answerElement.dataset.correct = answer.correct;

                answers.appendChild(answerElement);

                answerElement.addEventListener('click', () => {
                    if (!enableEdit) return;
                    answerElement.classList.toggle('active');
                });
            });

            enableEdit = true;
        });
}

// Check answers and display the result
function checkAnswers() {
    enableEdit = false;

    const answers = document.querySelectorAll('.answer');
    let isCorrect = true;

    answers.forEach((answer) => {
        answer.classList.remove('btn-outline-secondary');

        const isSelected = answer.classList.contains('active');
        const isCorrectAnswer = answer.dataset.correct === 'true';

        if (isSelected && !isCorrectAnswer) {
            isCorrect = false;
            answer.classList.add('btn-danger');
        } else if (!isSelected && isCorrectAnswer) {
            isCorrect = false;
            answer.classList.add('btn-success', 'opacity-50');
        } else if (isSelected && isCorrectAnswer) {
            answer.classList.add('btn-success');
        }

        answer.classList.remove('active');
    });

    const result = document.getElementById('result');
    result.textContent = `Odpowiedziałeś ${isCorrect ? 'poprawnie' : 'niepoprawnie'}.`;
    result.classList.toggle('text-success', isCorrect);
    result.classList.toggle('text-danger', !isCorrect);

    // Show/Hide buttons
    document.getElementById('check-answers-button').classList.add('d-none');
    document.getElementById('next-question-button').classList.remove('d-none');
}