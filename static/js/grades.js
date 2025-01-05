// Function to fetch grades data
async function fetchData() {
    try {
        const response = await fetch('/api/get-grades/');
        if (!response.ok) {
            throw new Error(`Network response was not ok: ${response.status}`);
        }
        const json = await response.json();
        document.getElementById('error-alert').classList.add('d-none');
        return json;
    } catch (error) {
        console.error('Error fetching grades:', error);
        document.getElementById('error-alert').classList.remove('d-none');
        document.getElementById('error-alert-additional-text').innerText = error;
        markProgressBarAsFailed();
        document.getElementById('error-alert-link').onclick = () => {
            resetProgressBars();
            main();
        }
        return [];
    }
}

// Function to calculate average grade
function calculateAverage(courses) {
    const sum = courses.reduce((acc, course) => {
        const courseSum = course.grades.reduce(
            (courseAcc, grade) => courseAcc + (!grade.counts_into_average ? 0 : grade.value * course.ects),
            0
        );
        return acc + courseSum;
    }, 0);

    const totalWeight = courses.reduce((acc, course) => {
        const courseWeight = course.grades.reduce(
            (courseAcc, grade) => courseAcc + (!grade.counts_into_average ? 0 : course.ects),
            0
        );
        return acc + courseWeight;
    }, 0);

    return (sum / totalWeight).toFixed(2);
}

// Function to render grades
function renderGrades(courses) {
    const table_body = document.getElementById('grades');
    table_body.innerHTML = '';

    courses.forEach((course) => {
        const gradeElement = document.createElement('tr');
        let statusClass = '';

        if (course.passing_status === 'passed') {
            statusClass = 'text-success';
        } else if (course.passing_status === 'failed') {
            statusClass = 'text-danger';
        } else if (course.passing_status === 'not_yet_passed') {
            statusClass = '';
        }

        gradeElement.innerHTML = `
            <td>${course.course_name}</td>
            <td>${course.ects}</td>
            <td class="${statusClass}">${course.grades.map((grade) => grade.value_symbol).join('; ') || '-'}</td>
        `;
        table_body.appendChild(gradeElement);
    });

    const average = calculateAverage(courses);
    document.getElementById('average').innerText = average === 'NaN' ? '-' : average;
}

// Function to populate term-select dropdown
function populateTermSelect(terms) {
    const today = new Date();
    const termSelect = document.getElementById('term-select');
    termSelect.parentElement.classList.remove('spinner-border');
    termSelect.innerHTML = '';
    terms.forEach((term) => {
        const option = document.createElement('option');
        option.value = term.id;
        option.text = term.name;
        if (today >= new Date(term.start_date) && today <= new Date(term.end_date)) {
            option.selected = true;
        }
        termSelect.appendChild(option);
    });
    termSelect.disabled = false;
}

// Main function to fetch and render grades and populate terms
async function main() {
    animateProgressBars();
    let data = await fetchData();
    let courses = data.courses;

    populateTermSelect(data.terms);

    const termSelect = document.getElementById('term-select');
    let selectedTerm = termSelect.value;
    let filteredCourses = selectedTerm ? courses.filter((course) => course.term_id === selectedTerm) : courses;
    renderGrades(filteredCourses);

    // Add event listener to term-select to filter grades
    termSelect.addEventListener('change', () => {
        const selectedTerm = termSelect.value;
        const filteredCourses = selectedTerm ? courses.filter((course) => course.term_id === selectedTerm) : courses;
        renderGrades(filteredCourses);
    });
}

function animateProgressBars() {
    // Get all progress bars
    const progressBars = document.querySelectorAll('.progress-bar');
    const indexes = [0, 1, 2]; // Specify the indexes to fill
    const fillDuration = 3000; // Duration to fill each bar in milliseconds

    // Function to animate a single progress bar
    function animateProgressBar(index) {
        if (index >= indexes.length) return; // Stop if all specified bars are filled

        let progress = 0; // Start at 0%

        const interval = setInterval(() => {
            progress += 1; // Increment progress
            progressBars.forEach((bar) => {
                if (parseInt(bar.dataset.progressBarIndex) === indexes[index] && progress === parseInt(bar.ariaValueNow) + 1) {
                    bar.style.width = `${progress}%`;
                    bar.ariaValueNow = progress;
                }
            });

            if (progress >= 100) {
                clearInterval(interval); // Stop animation at 100%
                animateProgressBar(index + 1); // Move to the next progress bar
            }
        }, fillDuration / 100); // Update every 30ms (3s / 100 steps)
    }

    animateProgressBar(0); // Start with the first index
}

function markProgressBarAsFailed() {
    const progressBars = document.querySelectorAll('.progress-bar');
    progressBars.forEach((bar) => {
        bar.classList.add('bg-danger');
    });
    finishProgressBar();
}

function resetProgressBars() {
    // Get all progress bars
    const progressBars = document.querySelectorAll('.progress-bar');
    progressBars.forEach((bar) => {
        bar.style.width = '0%'; // Reset width to 0%
        bar.ariaValueNow = 0;
        bar.classList.remove('bg-danger');
    });
}

function finishProgressBar() {
    const progressBars = document.querySelectorAll('.progress-bar');
    progressBars.forEach((bar) => {
        bar.style.width = '100%'; // Set width to 100%
        bar.ariaValueNow = 100;
    });
}


// Execute main function on page load
window.onload = main;
