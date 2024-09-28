let enableEdit = false;

document.addEventListener('DOMContentLoaded', function () {
    fetchQuestion();

    document.getElementById('check-answers-button').addEventListener('click', checkAnswers);
    document.getElementById('next-question-button').addEventListener('click', function () {
        fetchQuestion();
        document.getElementById('result').innerHTML = '';
        document.getElementById('check-answers-button').classList.remove('is-hidden');
        document.getElementById('next-question-button').classList.add('is-hidden');
    });
});

// function to fetch random question from the server and display it
function fetchQuestion() {
    fetch('/api/random-question-for-user/')
        .then(async response => {
            if (!response.ok) {
                document.getElementById('pop-quiz').classList.add('is-hidden');
                document.getElementById('pop-quiz-not-available').classList.remove('is-hidden');
            }
            const data = await response.json();
            let question = document.getElementById('question');
            question.innerHTML = `${data.id}. ${data.question}`;
            let answers = document.getElementById('answers');
            answers.innerHTML = '';
            let quizTitle = document.getElementById('quiz-title');
            quizTitle.innerHTML = data.quiz_title;
            quizTitle.href = `/quizzes/${data.quiz_id}/?question=${data.id}`;
            data.answers.forEach(function (answer) {
                let answerElement = document.createElement('button');
                answerElement.className = 'answer button is-soft is-small is-fullwidth';
                answerElement.innerHTML = answer.answer;
                answerElement.dataset.correct = answer.correct;
                answers.appendChild(answerElement);
                answerElement.addEventListener('click', function () {
                    if (!enableEdit) {
                        return;
                    }
                    answerElement.classList.toggle('is-info');
                });
            });
            enableEdit = true;
        });
}

// function to check the selected answers and display the result
function checkAnswers() {
    enableEdit = false;
    let answers = document.querySelectorAll('.answer');
    let isCorrect = true;
    answers.forEach(answer => {
        answer.classList.remove('is-soft');
        const isSelected = answer.classList.contains('is-info');
        const isCorrectAnswer = answer.dataset.correct === 'true';

        if (isSelected && !isCorrectAnswer) {
            isCorrect = false;
            answer.classList.add('is-danger');
        } else if (!isSelected && isCorrectAnswer) {
            isCorrect = false;
            answer.classList.add('is-success', 'is-soft');
        } else if (isSelected && isCorrectAnswer) {
            answer.classList.add('is-success');
        }

        answer.classList.remove('is-info');
    });
    let result = document.getElementById('result');
    result.innerHTML = `Odpowiedziałeś ${isCorrect ? 'poprawnie' : 'niepoprawnie'}.`;
    result.classList.toggle('has-text-success', isCorrect);
    result.classList.toggle('has-text-danger', !isCorrect);
    const checkAnswersButton = document.getElementById('check-answers-button');
    const nextQuestionButton = document.getElementById('next-question-button');
    checkAnswersButton.classList.add('is-hidden');
    nextQuestionButton.classList.remove('is-hidden');
}
