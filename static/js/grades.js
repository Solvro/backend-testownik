
        // Function to fetch grades data
        async function fetchGrades() {
            try {
                const response = await fetch('/api/get-grades/');
                return await response.json();
            } catch (error) {
                console.error('Error fetching grades:', error);
                return [];
            }
        }

        // Function to fetch all courses data
        async function fetchAllCourses() {
            try {
                const response = await fetch('/api/get-courses/');
                return await response.json();
            } catch (error) {
                console.error('Error fetching courses:', error);
                return [];
            }
        }

        async function addMissingCourses(grades) {
            const courses = await fetchAllCourses();
            const courseIds = grades.map(grade => grade.course_edition.course.id);
            const missingCourses = courses.filter(course => !courseIds.includes(course.id));
            let newGrades = [];
            missingCourses.forEach(course => {
                course.terms.forEach(term => {
                    newGrades.push({
                        course_edition: {
                            course: course,
                            term: term
                        },
                        weight: course.ects_credits_simplified, // It's correct to use this here as it's being set as a correct value in the backend
                        value: "-"
                    });
                });
            });
            return grades.concat(newGrades);
        }

        // Function to calculate average grade
        function calculateAverage(grades) {
            const sum = grades.reduce((acc, grade) => acc + (grade.value === "-" ? 0 : grade.value * grade.weight), 0);
            const totalWeight = grades.reduce((acc, grade) => acc + (grade.value === "-" ? 0 : grade.weight), 0);
            return (sum / totalWeight).toFixed(2);
        }

        // Function to render grades
        function renderGrades(grades) {
            const table_body = document.getElementById('grades');
            table_body.innerHTML = '';

            grades.forEach(grade => {
                const gradeElement = document.createElement('tr');
                gradeElement.innerHTML = `
                    <td>${grade.course_edition.course.name.pl}</td>
                    <td>${grade.weight}</td>
                    <td>${grade.value}</td>
                `;
                table_body.appendChild(gradeElement);
            });

            const average = calculateAverage(grades);
            document.getElementById('average').innerText = average === "NaN" ? "-" : average;
        }

        // Function to populate term-select dropdown
        function populateTermSelect(terms) {
            const today = new Date();
            const termSelect = document.getElementById('term-select');
            termSelect.parentElement.classList.remove('is-loading');
            termSelect.innerHTML = '';
            terms.forEach(term => {
                const option = document.createElement('option');
                option.value = term.id;
                option.text = term.name.pl;
                if (today >= new Date(term.start_date) && today <= new Date(term.end_date)) {
                    option.selected = true;
                }
                termSelect.appendChild(option);
            });
        }

        // Function to extract unique terms from grades data
        function extractUniqueTerms(grades) {
            const termsMap = new Map();
            grades.forEach(grade => {
                const term = grade.course_edition.term;
                if (!termsMap.has(term.id)) {
                    termsMap.set(term.id, term);
                }
            });
            return Array.from(termsMap.values());
        }

        // Main function to fetch and render grades and populate terms
        async function main() {
            let grades = await fetchGrades();

            grades.sort((a, b) => a.course_edition.course.name.pl.localeCompare(b.course_edition.course.name.pl));

            populateTermSelect(extractUniqueTerms(grades));

            const termSelect = document.getElementById('term-select');
            let selectedTerm = termSelect.value;
            let filteredGrades = selectedTerm ? grades.filter(grade => grade.course_edition.term.id === selectedTerm) : grades;
            renderGrades(filteredGrades);

            // Add event listener to term-select to filter grades
            termSelect.addEventListener('change', () => {
                const selectedTerm = termSelect.value;
                const filteredGrades = selectedTerm ? grades.filter(grade => grade.course_edition.term.id === selectedTerm) : grades;
                renderGrades(filteredGrades);
            });

            // Add missing courses
            grades = await addMissingCourses(grades);
            grades.sort((a, b) => a.course_edition.course.name.pl.localeCompare(b.course_edition.course.name.pl));

            populateTermSelect(extractUniqueTerms(grades));

            selectedTerm = termSelect.value;
            filteredGrades = selectedTerm ? grades.filter(grade => grade.course_edition.term.id === selectedTerm) : grades;
            renderGrades(filteredGrades);
        }

        // Execute main function on page load
        window.onload = main;
