import sys

def main():
    print(f"Python version: {sys.version}")
    
    try:
        import torch
        print(f"PyTorch version: {torch.__version__}")
        print(f"CUDA available: {torch.cuda.is_available()}")
    except ImportError as e:
        print(f"Failed to import PyTorch: {e}")
        sys.exit(1)

    try:
        import torch_geometric
        print(f"PyTorch Geometric version: {torch_geometric.__version__}")
    except ImportError as e:
        print(f"Failed to import PyTorch Geometric: {e}")
        sys.exit(1)

    print("\n✅ PyTorch and PyTorch Geometric are successfully installed and imported!")

if __name__ == "__main__":
    main()
