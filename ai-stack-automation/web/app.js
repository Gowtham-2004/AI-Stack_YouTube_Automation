const topicInput = document.getElementById("topic");
const generateButton = document.getElementById("generateButton");
const stageEl = document.getElementById("stage");
const messageEl = document.getElementById("message");
const progressBarEl = document.getElementById("progressBar");
const progressTextEl = document.getElementById("progressText");
const statusBadgeEl = document.getElementById("statusBadge");
const sceneGridEl = document.getElementById("sceneGrid");
const resultCardEl = document.getElementById("resultCard");
const videoPathEl = document.getElementById("videoPath");
const videoPreviewEl = document.getElementById("videoPreview");

let activeJobId = null;
let pollTimer = null;

function renderInitialScenes() {
  const cards = Array.from({ length: 12 }, (_, index) => {
    const sceneNumber = index + 1;
    return `
      <article class="scene-card">
        <h3>Scene ${sceneNumber.toString().padStart(2, "0")}</h3>
        <p>Waiting for a generated storyboard.</p>
        <span class="scene-pill">Pending</span>
      </article>
    `;
  }).join("");
  sceneGridEl.innerHTML = cards;
}

function setStatusBadge(status) {
  statusBadgeEl.className = `status-badge ${status}`;
  statusBadgeEl.textContent = status.charAt(0).toUpperCase() + status.slice(1);
}

function renderJob(job) {
  stageEl.textContent = job.stage;
  messageEl.textContent = job.error || job.message;
  progressBarEl.style.width = `${job.progress || 0}%`;
  progressTextEl.textContent = `${job.progress || 0}%`;
  setStatusBadge(job.status);

  const scenes = job.scenes || [];
  if (scenes.length) {
    sceneGridEl.innerHTML = scenes.map((scene) => `
      <article class="scene-card">
        <h3>Scene ${String(scene.scene_number).padStart(2, "0")}</h3>
        <p>${scene.visual_focus || "Scene"}</p>
        <p>${scene.message || ""}</p>
        <span class="scene-pill ${scene.status}">${scene.status.replaceAll("_", " ")}</span>
      </article>
    `).join("");
  }

  if (job.status === "completed" && job.video_url) {
    resultCardEl.classList.remove("hidden");
    videoPathEl.textContent = job.video_path;
    videoPreviewEl.src = job.video_url;
  } else {
    resultCardEl.classList.add("hidden");
    videoPreviewEl.removeAttribute("src");
  }
}

async function fetchJob(jobId) {
  const response = await fetch(`/api/jobs/${jobId}`);
  if (!response.ok) {
    throw new Error("Failed to fetch job status.");
  }
  return response.json();
}

async function pollJob() {
  if (!activeJobId) {
    return;
  }

  try {
    const job = await fetchJob(activeJobId);
    renderJob(job);

    if (job.status === "completed" || job.status === "failed") {
      window.clearInterval(pollTimer);
      pollTimer = null;
      generateButton.disabled = false;
    }
  } catch (error) {
    window.clearInterval(pollTimer);
    pollTimer = null;
    generateButton.disabled = false;
    stageEl.textContent = "Status unavailable";
    messageEl.textContent = error.message;
    setStatusBadge("failed");
  }
}

async function createJob() {
  const topic = topicInput.value.trim();
  if (!topic) {
    topicInput.focus();
    return;
  }

  generateButton.disabled = true;
  resultCardEl.classList.add("hidden");
  videoPreviewEl.pause();
  activeJobId = null;
  stageEl.textContent = "Submitting topic";
  messageEl.textContent = "Creating a new generation job.";
  progressBarEl.style.width = "2%";
  progressTextEl.textContent = "2%";
  setStatusBadge("running");

  const response = await fetch("/api/jobs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ topic }),
  });

  const job = await response.json();
  if (!response.ok) {
    generateButton.disabled = false;
    throw new Error(job.error || "Failed to create job.");
  }

  activeJobId = job.job_id;
  renderJob(job);
  pollTimer = window.setInterval(pollJob, 2000);
  pollJob();
}

generateButton.addEventListener("click", () => {
  createJob().catch((error) => {
    stageEl.textContent = "Unable to start";
    messageEl.textContent = error.message;
    setStatusBadge("failed");
    generateButton.disabled = false;
  });
});

topicInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    generateButton.click();
  }
});

renderInitialScenes();
