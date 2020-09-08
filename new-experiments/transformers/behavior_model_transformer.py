import json
import sys
import h5py

import tensorflow as tf

from keras_transformer import get_model
from keras_transformer import decode
from keras_transformer import get_custom_objects as get_encoder_custom_objects

from keras.callbacks import ModelCheckpoint, EarlyStopping
from keras.layers import Dot, Bidirectional, Concatenate, Convolution2D, Dense, Dropout, Embedding, Flatten, GRU, Input, Lambda, MaxPooling2D, Multiply, Reshape
from keras.models import load_model, Model
from keras.preprocessing.text import Tokenizer

from keras_pos_embd import PositionEmbedding

from tqdm import tqdm

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import numpy as np
import pandas as pd

# Kasteren dataset
DIR = '/sensor2vec/kasteren_dataset/'
# Dataset with vectors but without the action timestamps
DATASET_CSV = DIR + 'base_kasteren_reduced.csv'
DATASET_NO_TIME = DIR + 'dataset_no_time.json'
# dataset with actions transformed with time periods
DATASET_ACTION_PERIODS = DIR + 'kasteren_action_periods.csv'
# List of unique activities in the dataset
UNIQUE_ACTIVITIES = DIR + 'unique_activities.json'
# List of unique actions in the dataset
UNIQUE_ACTIONS = DIR + 'unique_actions.json'
# List of unique actions in the dataset taking into account time periods
UNIQUE_TIME_ACTIONS = DIR + 'unique_time_actions.json'

#number of input actions for the model
INPUT_ACTIONS = 5
#Number of elements in the action's embbeding vector
ACTION_EMBEDDING_LENGTH = 50

#best model in the training
BEST_MODEL = '/results/best_model.hdf5'

# if time is being taken into account
TIME = False

BATCH_SIZE = 128

"""
Load the best model saved in the checkpoint callback
"""
def select_best_model():
    model = load_model(BEST_MODEL)
    return model

"""
Function used to visualize the training history
metrics: Visualized metrics,
save: if the png are saved to disk
history: training history to be visualized
"""
def plot_training_info(metrics, save, history):
    # summarize history for accuracy
    if 'accuracy' in metrics:
        
        plt.plot(history['accuracy'])
        plt.plot(history['val_accuracy'])
        plt.title('model accuracy')
        plt.ylabel('accuracy')
        plt.xlabel('epoch')
        plt.legend(['train', 'test'], loc='upper left')
        if save == True:
            plt.savefig('/results/accuracy.png')
            plt.gcf().clear()
        else:
            plt.show()

    # summarize history for loss
    if 'loss' in metrics:
        plt.plot(history['loss'])
        plt.plot(history['val_loss'])
        plt.title('model loss')
        plt.ylabel('loss')
        plt.xlabel('epoch')
        #plt.ylim(1e-3, 1e-2)
        plt.yscale("log")
        plt.legend(['train', 'test'], loc='upper left')
        if save == True:
            plt.savefig('/results/loss.png')
            plt.gcf().clear()
        else:
            plt.show()

"""
Prepares the training examples of secuences based on the total actions, using
embeddings to represent them.
Input
    df:Pandas DataFrame with timestamp, sensor, action, event and activity
    unique_actions: list of actions
Output:
    X: array with action index sequences
    y: array with action index for next action
    tokenizer: instance of Tokenizer class used for action/index convertion
    
"""            
def prepare_x_y(df, unique_actions):
    #recover all the actions in order.
    actions = df['action'].values
#    print actions.tolist()
#    print actions.tolist().index('HallBedroomDoor_1')
    # Use tokenizer to generate indices for every action
    # Very important to put lower=False, since the Word2Vec model
    # has the action names with some capital letters
    tokenizer = Tokenizer(lower=False)
    tokenizer.fit_on_texts(actions.tolist())
    action_index = tokenizer.word_index  
#    print action_index
    #translate actions to indexes
    actions_by_index = []
    
    print((len(actions)))
    for action in actions:
#        print action
        actions_by_index.append(action_index[action])

    #Create the trainning sets of sequences with a lenght of INPUT_ACTIONS
    last_action = len(actions) - 1
    X = []
    y = []
    for i in range(last_action-INPUT_ACTIONS):
        X.append(actions_by_index[i:i+INPUT_ACTIONS])
        #represent the target action as a onehot for the softmax
        target_action = ''.join(i for i in actions[i+INPUT_ACTIONS] if not i.isdigit()) # remove the period if it exists
        y.append(unique_actions.index(target_action))
    return X, y, tokenizer   
    
"""
Prepares the training examples of secuences based on the total actions, using 
one hot vectors to represent them
Input
    df:Pandas DataFrame with timestamp, sensor, action, event and activity
    unique_actions: list of actions
Output:
    X: array with action index sequences
    y: array with action index for next action    
"""            
def prepare_x_y_onehot(df, unique_actions):
    #recover all the actions in order.
    actions = df['action'].values
    #translate actions to onehots
    actions_by_onehot = [] 
    for action in actions:
        onehot = [0] * len(unique_actions)
        action_index = unique_actions.index(action)
        onehot[action_index] = 1
        actions_by_onehot.append(onehot)

    #Create the trainning sets of sequences with a lenght of INPUT_ACTIONS
    last_action = len(actions) - 1
    X = []
    y = []
    for i in range(last_action-INPUT_ACTIONS):
        X.append(actions_by_onehot[i:i+INPUT_ACTIONS])
        #represent the target action as a onehot for the softmax
        target_action = actions_by_onehot[i+INPUT_ACTIONS]
        y.append(target_action)
    return X, y 

def main(argv):
    print(('*' * 20))
    print('Loading dataset...')
    sys.stdout.flush()
    #dataset of activities
    if TIME:
        DATASET = DATASET_ACTION_PERIODS
    else:
        DATASET = DATASET_CSV
    df_dataset = pd.read_csv(DATASET, parse_dates=[[0, 1]], header=None, index_col=0, sep=' ')
    df_dataset.columns = ['sensor', 'action', 'event', 'activity']
    df_dataset.index.names = ["timestamp"]    
    # we only need the actions without the period to calculate the onehot vector for y, because we are only predicting the actions
    unique_actions = json.load(open(UNIQUE_ACTIONS, 'r'))
    total_actions = len(unique_actions)
    
    print(('*' * 20))
    print('Preparing dataset...')
    sys.stdout.flush()
    # Prepare sequences using action indices
    X, y, tokenizer = prepare_x_y(df_dataset, unique_actions)    

    #divide the examples in training and validation
    total_examples = len(X)
    test_per = 0.2
    limit = int(test_per * total_examples)
    X_train = X[limit:]
    X_test = X[:limit]
    y_train = y[limit:]
    y_test = y[:limit]
    print(('Different actions:', total_actions))
    print(('Total examples:', total_examples))
    print(('Train examples:', len(X_train), len(y_train))) 
    print(('Test examples:', len(X_test), len(y_test)))
    sys.stdout.flush()  
    X_train = np.array(X_train)
    y_train = np.array(y_train)
    X_test = np.array(X_test)
    y_test = np.array(y_test)
    print('Shape (X,y):')
    print((X_train.shape))
    print((y_train.shape))

    token_dict = {
        '<PAD>': 0,
        '<START>': 1,
        '<END>': 2,
    }

    X_train = X_train.flatten()
    X_test = X_test.flatten()

    X_train = list(map(str,X_train))
    X_test = list(map(str,X_test))

    for token in X_train:
        if token not in token_dict:
            token_dict[token] = len(token_dict)

    print(token_dict)

    encoder_inputs_no_padding = []
    encoder_inputs, decoder_inputs, decoder_outputs = [], [], []
    for i in range(1, len(X_train) - 1):
        encode_tokens, decode_tokens = X_train[:i], X_train[i:]
        encode_tokens = ['<START>'] + encode_tokens + ['<END>'] + ['<PAD>'] * (len(X_train) - len(encode_tokens))
        output_tokens = decode_tokens + ['<END>', '<PAD>'] + ['<PAD>'] * (len(X_train) - len(decode_tokens))
        decode_tokens = ['<START>'] + decode_tokens + ['<END>'] + ['<PAD>'] * (len(X_train) - len(decode_tokens))
        encode_tokens = list(map(lambda x: token_dict[x], encode_tokens))
        decode_tokens = list(map(lambda x: token_dict[x], decode_tokens))
        output_tokens = list(map(lambda x: [token_dict[x]], output_tokens))
        encoder_inputs_no_padding.append(encode_tokens[:i + 2])
        encoder_inputs.append(encode_tokens)
        decoder_inputs.append(decode_tokens)
        decoder_outputs.append(output_tokens)

    executions = 100
    accuracies_avg = np.array([0, 0, 0, 0, 0])
    accuracies_best = np.array([0, 0, 0, 0, 0])

    for i in range(0, executions):
        
        print(('*' * 20))
        print('Building model...')
        sys.stdout.flush()

        model = get_model(
            token_num=len(token_dict),
            embed_dim=50,
            encoder_num=3,
            decoder_num=2,
            head_num=5,
            hidden_dim=50,
            attention_activation='relu',
            feed_forward_activation='relu',
            dropout_rate=0.05,
            embed_weights=np.random.random((len(token_dict), 50)),
        )

        model.compile(
            optimizer='adam',
            loss='sparse_categorical_crossentropy',
        )

        model.summary()

        model.fit(
            x=[np.asarray(encoder_inputs * 1000), np.asarray(decoder_inputs * 1000)],
            y=np.asarray(decoder_outputs * 1000),
            epochs=5,
        )

        decoded = decode(
            model,
            encoder_inputs_no_padding,
            start_token=token_dict['<START>'],
            end_token=token_dict['<END>'],
            pad_token=token_dict['<PAD>'],
            max_len=5,
        )
        token_dict_rev = {v: k for k, v in token_dict.items()}
        for i in range(len(decoded)):
            print(' '.join(map(lambda x: token_dict_rev[x], decoded[i][1:-1])))

        # https://www.tensorflow.org/api_docs/python/tf/keras/backend/clear_session
        tf.keras.backend.clear_session()

        break

        print(('************ FIN ************\n' * 3))
    
    accuracies_avg = [x / executions for x in accuracies_avg]

    print(('************ AVG ************\n'))
    print(accuracies_avg)
    print(('************ BEST ************\n'))
    print(accuracies_best)

    print(('************ FIN MEDIA Y MEJOR RESULTADO ************\n' * 3))

if __name__ == "__main__":
    main(sys.argv)