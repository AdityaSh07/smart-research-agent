const form = document.getElementById("compose-form");
const topicInput = document.getElementById("topic");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");
const resultMetaEl = document.getElementById("result-meta");
const button = document.getElementById("generate-btn");

const generationStatusSection = document.getElementById("generation-status");
const generationLog = document.getElementById("generation-log");
const sectionReviewSection = document.getElementById("section-review");
const sectionsContainer = document.getElementById("sections-container");
const planTitleEl = document.getElementById("plan-title");
const submitReviewBtn = document.getElementById("submit-review-btn");
const reviewStatusEl = document.getElementById("review-status");

let currentSessionId = null;
let sectionStates = {}; // Track {original, current, isEditing} for each section

// Reset form and state for new generation
function resetForm() {
  topicInput.value = "";
  statusEl.textContent = "";
  resultEl.textContent = "Write a topic and click Generate Article.";
  resultMetaEl.textContent = "No content generated yet.";
  generationStatusSection.style.display = "none";
  sectionReviewSection.style.display = "none";
  generationLog.innerHTML = "";
  currentSessionId = null;
  sectionStates = {};
  button.disabled = false;
  submitReviewBtn.disabled = false;
  reviewStatusEl.textContent = "";
}

// Add log message to generation log
function addLog(message, type = "default") {
  const p = document.createElement("p");
  p.textContent = message;
  if (type === "tavily") {
    p.className = "log-tavily";
  } else if (type === "research") {
    p.className = "log-research";
  }
  generationLog.appendChild(p);
  generationLog.scrollTop = generationLog.scrollHeight;
}

// Initialize generation status display
function showGenerationStatus() {
  generationStatusSection.style.display = "block";
  sectionReviewSection.style.display = "none";
  resultEl.textContent = "Awaiting section generation...";
  resultMetaEl.textContent = "";
  generationLog.innerHTML = "";
  addLog("Starting research process...");
  addLog("Checking Tavily integration...", "tavily");
}

// Render sections for review with full edit capability
function renderSections(sections, planTitle) {
  planTitleEl.textContent = planTitle;
  sectionsContainer.innerHTML = "";
  sectionStates = {};

  Object.entries(sections).forEach(([sectionId, originalContent]) => {
    const sectionIdNum = parseInt(sectionId);
    
    // Initialize state for this section
    sectionStates[sectionIdNum] = {
      original: originalContent,
      current: originalContent,
      isEditing: false
    };

    const sectionItem = document.createElement("div");
    sectionItem.className = "section-item";
    sectionItem.dataset.sectionId = sectionIdNum;

    const header = document.createElement("div");
    header.className = "section-header";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "section-checkbox";
    checkbox.checked = true;
    checkbox.dataset.sectionId = sectionIdNum;

    const title = document.createElement("span");
    title.className = "section-title";
    title.textContent = `Section ${sectionIdNum}`;
    
    // Show edit indicator
    const editIndicator = document.createElement("span");
    editIndicator.className = "edit-indicator";
    editIndicator.textContent = "";
    editIndicator.style.fontSize = "0.8em";
    editIndicator.style.marginLeft = "8px";
    editIndicator.style.color = "#d35400";
    title.appendChild(editIndicator);

    const toggle = document.createElement("button");
    toggle.className = "section-toggle";
    toggle.type = "button";
    toggle.textContent = "▼";
    toggle.onclick = (e) => {
      e.preventDefault();
      const contentDiv = sectionItem.querySelector(".section-content");
      contentDiv.classList.toggle("collapsed");
      toggle.textContent = contentDiv.classList.contains("collapsed") ? "▶" : "▼";
    };

    header.appendChild(checkbox);
    header.appendChild(title);
    header.appendChild(toggle);

    const contentDiv = document.createElement("div");
    contentDiv.className = "section-content";

    const viewDiv = document.createElement("div");
    viewDiv.className = "section-view";

    const textDiv = document.createElement("div");
    textDiv.className = "section-text";
    textDiv.textContent = originalContent;

    const viewBtnContainer = document.createElement("div");
    viewBtnContainer.className = "section-buttons";

    const editBtn = document.createElement("button");
    editBtn.className = "edit-btn";
    editBtn.type = "button";
    editBtn.textContent = "Edit Section";
    editBtn.onclick = (e) => {
      e.preventDefault();
      viewDiv.style.display = "none";
      editDiv.style.display = "flex";
      sectionStates[sectionIdNum].isEditing = true;
      textarea.focus();
    };

    viewBtnContainer.appendChild(editBtn);
    viewDiv.appendChild(textDiv);
    viewDiv.appendChild(viewBtnContainer);

    const editDiv = document.createElement("div");
    editDiv.className = "section-edit";
    editDiv.style.display = "none";

    const textarea = document.createElement("textarea");
    textarea.value = originalContent;
    textarea.placeholder = "Edit section content. Make your changes and click Save.";

    const editBtnContainer = document.createElement("div");
    editBtnContainer.className = "section-buttons";

    const saveBtn = document.createElement("button");
    saveBtn.className = "save-btn";
    saveBtn.type = "button";
    saveBtn.textContent = "Save Changes";
    saveBtn.onclick = (e) => {
      e.preventDefault();
      const newContent = textarea.value;
      sectionStates[sectionIdNum].current = newContent;
      textDiv.textContent = newContent;
      viewDiv.style.display = "block";
      editDiv.style.display = "none";
      sectionStates[sectionIdNum].isEditing = false;
      
      // Show edit indicator if content changed
      editIndicator.textContent = newContent !== originalContent ? "[EDITED]" : "";
    };

    const cancelBtn = document.createElement("button");
    cancelBtn.className = "cancel-btn";
    cancelBtn.type = "button";
    cancelBtn.textContent = "Discard Changes";
    cancelBtn.onclick = (e) => {
      e.preventDefault();
      textarea.value = sectionStates[sectionIdNum].current;
      viewDiv.style.display = "block";
      editDiv.style.display = "none";
      sectionStates[sectionIdNum].isEditing = false;
    };
    
    const resetBtn = document.createElement("button");
    resetBtn.className = "reset-btn";
    resetBtn.type = "button";
    resetBtn.textContent = "Reset to Original";
    resetBtn.style.background = "linear-gradient(135deg, #9ca3af, #6b7280)";
    resetBtn.onclick = (e) => {
      e.preventDefault();
      textarea.value = originalContent;
      sectionStates[sectionIdNum].current = originalContent;
      textDiv.textContent = originalContent;
      viewDiv.style.display = "block";
      editDiv.style.display = "none";
      sectionStates[sectionIdNum].isEditing = false;
      editIndicator.textContent = "";
    };

    editBtnContainer.appendChild(saveBtn);
    editBtnContainer.appendChild(cancelBtn);
    editBtnContainer.appendChild(resetBtn);

    editDiv.appendChild(textarea);
    editDiv.appendChild(editBtnContainer);

    contentDiv.appendChild(viewDiv);
    contentDiv.appendChild(editDiv);

    sectionItem.appendChild(header);
    sectionItem.appendChild(contentDiv);
    sectionsContainer.appendChild(sectionItem);
  });
}

// Show section review section
function showSectionReview() {
  generationStatusSection.style.display = "none";
  sectionReviewSection.style.display = "block";
}

// Submit review feedback
submitReviewBtn.addEventListener("click", async (e) => {
  e.preventDefault();

  if (!currentSessionId) {
    reviewStatusEl.textContent = "Error: No session found.";
    return;
  }

  // Check if any sections are still in edit mode
  const stillEditing = Object.entries(sectionStates).filter(
    ([id, state]) => state.isEditing
  );
  if (stillEditing.length > 0) {
    reviewStatusEl.textContent = `Please save or discard changes for section(s): ${stillEditing.map(([id]) => id).join(", ")}`;
    return;
  }

  const approvedIds = [];
  const edits = {};

  // Collect approved sections and edits
  document.querySelectorAll(".section-checkbox").forEach((checkbox) => {
    const sectionId = parseInt(checkbox.dataset.sectionId);
    if (checkbox.checked) {
      approvedIds.push(sectionId);
      
      // Check if section was edited from original
      if (sectionStates[sectionId] && sectionStates[sectionId].current !== sectionStates[sectionId].original) {
        edits[sectionId] = sectionStates[sectionId].current;
      }
    }
  });

  if (approvedIds.length === 0) {
    reviewStatusEl.textContent = "Please approve at least one section.";
    return;
  }

  submitReviewBtn.disabled = true;
  reviewStatusEl.textContent = "Generating final article...";

  try {
    const response = await fetch(
      `/api/blog/review?session_id=${currentSessionId}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          approved_ids: approvedIds,
          edits: edits,
        }),
      }
    );

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Review submission failed.");
    }

    // Show final article
    sectionReviewSection.style.display = "none";
    generationStatusSection.style.display = "none";
    resultEl.textContent = data.final_md;
    resultMetaEl.textContent = `Saved as: ${data.saved_file}`;
    reviewStatusEl.textContent = "Article generated successfully!";
    statusEl.textContent = "Article generated successfully! You can generate a new article or modify the current one.";
    
    // Reset state for new generation
    button.disabled = false;
    button.textContent = "Generate Another Article";
    topicInput.value = "";
    currentSessionId = null;
    sectionStates = {};
    submitReviewBtn.disabled = false;
    
  } catch (error) {
    reviewStatusEl.textContent = "Request failed: " + String(error);
    statusEl.textContent = "Request failed: " + String(error);
    submitReviewBtn.disabled = false;
    button.disabled = false;
  }
});

// Form submission
form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const topic = topicInput.value.trim();
  if (!topic) {
    statusEl.textContent = "Please add a topic first.";
    return;
  }

  // Reset form state completely for new generation
  resetForm();
  button.disabled = true;
  button.textContent = "Generate Article";
  statusEl.textContent = "Starting generation...";
  submitReviewBtn.disabled = false;

  showGenerationStatus();

  try {
    addLog("Sending request to backend...");

    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Generation failed.");
    }

    currentSessionId = data.session_id;
    addLog("Session created successfully", "tavily");
    addLog(`Topic: ${data.topic}`, "research");

    // Simulate research process messages
    addLog("Gathering research data...", "research");
    addLog("Using Tavily for web search", "tavily");
    addLog("Generating article sections...", "research");

    // Show sections for review
    setTimeout(() => {
      addLog("Sections ready for review!");
      showSectionReview();
      renderSections(data.sections, data.plan_title);
      statusEl.textContent = "Please review and edit sections below.";
      button.disabled = false;
    }, 1000);
  } catch (error) {
    statusEl.textContent = "Request failed.";
    addLog("Error: " + String(error));
    generationStatusSection.style.display = "block";
    button.disabled = false;
  }
});

