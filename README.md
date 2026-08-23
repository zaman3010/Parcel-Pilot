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
   *(Note: For `MONGO_URI`, paste your connection string and replace `<username>` and `<password>` with the database user credentials you created in Step 4. Also replace `your_api_key_here` with your OpenRouter/OpenAI key)*

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
