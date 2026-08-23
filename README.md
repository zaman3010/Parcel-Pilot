# ParcelPilot

ParcelPilot is an AI-powered customer support and logistics platform that helps manage parcel deliveries, ticket escalation, and intelligent query responses via an LLM-driven chat agent. 

The project is split into a **FastAPI backend** and a **React/Vite frontend**.

## Data Storage Architecture

ParcelPilot uses a **dual-write persistence** system to ensure your data is always safe and accessible:
1. **MongoDB Atlas (Primary Cloud Database)**: Acts as the main data store. All tickets, orders, and interactions created by the AI agent are primarily pushed here.
2. **SQLite (Secondary Local Database)**: Acts as a local backup and offline reference. Every time data is pushed to MongoDB, it is simultaneously written to a local SQLite file (`backend/parcelpilot.db`).

## Prerequisites

Before you begin, ensure you have the following installed on your machine:
- **Node.js** (v18 or higher) and npm
- **Python** (3.11 or higher)
- **Git**

You will also need:
- An **OpenRouter** or OpenAI API Key (to power the AI Assistant)
- A **MongoDB Atlas** cluster URI

## 1. Clone the Repository

```bash
git clone https://github.com/zaman3010/Parcel-Pilot.git
cd Parcel-Pilot
```

## 2. Backend Setup

The backend handles AI generation, knowledge base (ChromaDB) vector embeddings, local SQLite syncing, and MongoDB connectivity.

1. **Navigate to the backend folder**:
   ```bash
   cd backend
   ```

2. **Create and activate a virtual environment**:
   - **Windows**:
     ```bash
     python -m venv venv
     venv\Scripts\activate
     ```
   - **Mac/Linux**:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```

3. **Install the dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **MongoDB Atlas Setup**:
   To connect the app to your own MongoDB cluster:
   - Go to [MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register) and create a free account/cluster.
   - Go to **Database Access** and create a new Database User (note down the username and password).
   - Go to **Network Access** and add your IP address (or `0.0.0.0/0` to allow all).
   - Go back to **Database**, click **Connect**, choose **Drivers** (Python), and copy the connection string.

5. **Environment Configuration**:
   Create a file named `.env` in the `backend/` directory and add the following keys:
   ```env
   OPENAI_API_KEY=your_api_key_here
   OPENAI_API_BASE=https://openrouter.ai/api/v1
   MONGO_URI=mongodb+srv://<username>:<password>@cluster0.example.mongodb.net/?appName=Cluster0
   ```
   *(Note: To connect to your own database, you **must** change the `MONGO_URI` in this `backend/.env` file. Paste your connection string here and replace `<username>` and `<password>` with the database user credentials you created in Step 4. If you aren't using a `.env` file, you can alternatively update the fallback `MONGO_URI` variable directly inside `backend/main.py` and `backend/tools.py`.)*

6. **Run the backend server**:
   ```bash
   python -m uvicorn main:app --reload
   ```
   The backend will start at `http://localhost:8000`.

## 3. Frontend Setup

The frontend provides the user interface for chatting with the agent and viewing ticket escalations.

1. **Open a new terminal window** and navigate to the frontend folder (from the project root):
   ```bash
   cd frontend
   ```

2. **Install node modules**:
   ```bash
   npm install
   ```

3. **Start the development server**:
   ```bash
   npm run dev
   ```

## 4. Usage

Once both servers are running:
1. Open your browser and navigate to `http://localhost:5173` (or the port Vite provides).
2. You can chat with the AI assistant, simulating customer queries or staff operations. The agent will read from the embedded vector database and interact with your MongoDB/SQLite databases to create orders and update tickets!

---

## 5. Architecture Note

- **Agent Design**: The system leverages LangGraph to build a stateful, graph-based agent workflow. It implements strict persona separation (Customer vs. Internal Staff) using dynamic system prompts and API orchestration. Interrupts are used to pause execution for human-in-the-loop verification before state-changing actions (like escalations).
- **Tool Design**: Tools are modularly bound to the LLM based on the active persona. For instance, customers only have access to knowledge search and basic escalation, while internal staff have access to advanced data querying and trend analysis (`analyze_trends`).
- **Document and Structured-Data Handling**: Unstructured policies and SOPs are handled via RAG using ChromaDB and OpenAI embeddings (`text-embedding-3-small`). Structured business data (orders, tickets) is stored in MongoDB Atlas, with a dual-write mechanism to a local SQLite database for local persistence and redundancy.
- **Source Reliability and Conflict Handling**: The LLM's system prompt dictates strict source precedence (e.g., Signed Agreement > Support Policy > Product Documentation). The agent is instructed to request human verification upon encountering data conflicts rather than hallucinating, and explicitly avoids deprecated policies.
- **Major Technical Trade-offs**: 
  1. **Dual-write persistence**: We chose to implement a dual-write pattern (MongoDB + SQLite) rather than relying solely on the cloud. This improves local development experience and offline redundancy, at the cost of slightly increased write latency.
  2. **LLM SQL Generation vs Fixed Endpoints**: We allowed the internal agent to generate SQL for trend analysis. This maximizes flexibility for staff to query cross-account data without needing infinite backend endpoints, trading off against strict query predictability.

## 6. Product Note

- **Additional Client Problem Addressed**: We tackled the problem of **Unverified Escalations**. Customers often try to escalate issues without providing crucial contact or order details. We addressed this by implementing a strict prompt flow that forces the AI to explicitly gather the Order ID and contact details *before* ever invoking the `escalate_order` tool.
- **What else we would build**: 
  - **Real-time Webhooks**: Integration with carrier APIs to automatically update ticket statuses in the background.
  - **Authentication / RBAC**: Moving beyond a simple UI dropdown to a full JWT-based authentication system to securely enforce persona constraints.
- **What was intentionally left out**: Complex mock carrier integrations. The data fetching is heavily localized to the databases we built rather than reaching out to external fake courier APIs, to keep the focus on the LLM reasoning and data retrieval.
- **Success Metric**: **Ticket Deflection Rate**. The primary metric to judge the product's usefulness is the percentage of customer queries that the AI successfully resolves on its own using RAG and database queries, without needing to invoke the `escalate_order` tool to loop in human staff.
