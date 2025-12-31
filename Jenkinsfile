pipeline {
    agent any
    
    environment {
        PYTHONPATH = "${WORKSPACE}"
    }
    
    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        
        stage('Setup Python Environment') {
            steps {
                script {
                    // Check if Python is available
                    sh 'python3 --version'
                    
                    // Create virtual environment
                    sh 'python3 -m venv venv'
                    
                    // Activate virtual environment and install dependencies
                    sh '''
                        source venv/bin/activate
                        pip install --upgrade pip
                        
                        # Install data-access-lib from Git repository
                        echo "Installing data-access-lib from Git repository..."
                        pip install git+https://github.com/blueenergy/data-access-lib.git
                        
                        # Install project dependencies
                        if [ -f requirements.txt ]; then
                            pip install -r requirements.txt
                        fi
                        
                        # Install test dependencies
                        if [ -f requirements-dev.txt ]; then
                            pip install -r requirements-dev.txt
                        fi
                    '''
                }
            }
        }
        
        stage('Static Code Analysis') {
            steps {
                script {
                    sh '''
                        source venv/bin/activate
                        echo "Running ruff code analysis..."
                        ruff check . --exclude venv/*
                    '''
                }
            }
        }
        
        stage('Run Unit Tests') {
            steps {
                script {
                    sh '''
                        source venv/bin/activate
                        echo "Running unit tests..."
                        python -m pytest tests/ -v --junit-xml=test-results.xml --cov=worker --cov=data_sources --cov-report=html:coverage-report --cov-report=term-missing
                    '''
                }
            }
        }
        
        stage('Integration Test') {
            when {
                anyOf {
                    branch 'main'
                    branch 'master'
                    buildingTag()
                }
            }
            steps {
                script {
                    sh '''
                        source venv/bin/activate
                        echo "Running integration tests..."
                        # Run pytest with integration tests
                        python -m pytest tests/ -v -k integration
                    '''
                }
            }
        }
        
        stage('Validate Strategy Params Integration') {
            steps {
                script {
                    sh '''
                        source venv/bin/activate
                        echo "Validating strategy parameters integration..."
                        python -c "
                        from quant_strategies.strategy_params.factory import create_strategy_with_params
                        from worker.simple_backtest_runner import SimpleBacktestRunner
                        print('✓ Strategy params integration validated')
                        "
                    '''
                }
            }
        }
    }
    
    post {
        always {
            // Publish test results
            publishTestResults testResultsPattern: 'test-results.xml'
            
            // Archive coverage report
            archiveArtifacts artifacts: 'coverage-report/**/*', fingerprint: true, allowEmptyArchive: true
            
            // Publish coverage report
            publishCoverage adapters: [
                jacocoAdapter('coverage-report/*/coverage.xml')
            ], 
            sourceFileResolver: sourceFiles('STORE_LAST_BUILD')
        }
        
        success {
            script {
                echo "Pipeline completed successfully!"
                echo "Coverage report available at: ${env.BUILD_URL}artifact/coverage-report/index.html"
            }
        }
        
        failure {
            script {
                echo "Pipeline failed! Please check the logs for details."
                currentBuild.result = 'FAILURE'
            }
        }
        
        unstable {
            script {
                echo "Pipeline completed with some issues."
            }
        }
    }
}